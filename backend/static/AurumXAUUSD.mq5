//+------------------------------------------------------------------+
//|                                              AurumXAUUSD.mq5     |
//|                       AURUM Terminal · XAU/USD AI Auto-Trader    |
//|                                                                  |
//|  Polls AURUM Terminal AI signals and auto-executes trades on     |
//|  MetaTrader 5 with risk-based position sizing, semi-auto         |
//|  confirmation, and scale-out at TP1 (move SL to breakeven).      |
//+------------------------------------------------------------------+
#property copyright "AURUM Terminal"
#property link      "https://aurum.terminal"
#property version   "1.00"
#property strict
#property description "AURUM AI Auto-Trader for XAU/USD"
#property description "Connects to AURUM Terminal API for dual-AI confirmed signals"

#include <Trade/Trade.mqh>

//--- Inputs
input group "=== AURUM API ==="
input string InpApiUrl       = "https://precious-trade-12.emergent.host"; // AURUM API URL (no trailing slash)
input string InpInterval     = "1h";                                       // Signal timeframe (1min/5min/15min/1h/4h/1day)
input string InpStrength     = "STRONG";                                   // Filter: STRONG or ANY
input int    InpPollSeconds  = 60;                                         // Poll interval in seconds

input group "=== Trade Settings ==="
input string InpSymbol       = "XAUUSD";                                   // Symbol (XAUUSD / XAUUSDm / GOLD etc.)
input bool   InpSemiAuto     = true;                                       // Show confirmation dialog before each trade
input double InpRiskPercent  = 1.0;                                        // Risk % of account balance per trade
input double InpFixedLot     = 0.0;                                        // Fixed lot (set >0 to override risk%)
input int    InpMaxPositions = 2;                                          // Max concurrent EA positions
input long   InpMagicNumber  = 20260101;                                   // EA Magic Number
input int    InpSlippage     = 50;                                         // Max slippage in points

input group "=== Scale-out Strategy ==="
input bool   InpUseScaleOut  = true;                                       // At TP1: close 50%, move SL to BE
input double InpScaleOutPct  = 50.0;                                       // % to close at TP1 (default 50%)

input group "=== Telegram Reporting ==="
input bool   InpReportToAurum = true;                                      // Send trade events to AURUM Telegram

//--- Globals
CTrade trade;
string last_signal_id = "";
datetime last_poll_time = 0;

//+------------------------------------------------------------------+
//| Initialization                                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagicNumber);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(InpSymbol);
   EventSetTimer(InpPollSeconds);

   Print("=================================");
   Print(" AURUM Terminal EA · v1.00");
   Print(" API:       ", InpApiUrl, "/api/ea/signal");
   Print(" Symbol:    ", InpSymbol);
   Print(" Interval:  ", InpInterval, "  Strength: ", InpStrength);
   Print(" Risk:      ", DoubleToString(InpRiskPercent, 2), "% per trade");
   Print(" Semi-auto: ", InpSemiAuto ? "YES" : "NO (full auto)");
   Print(" Max pos:   ", InpMaxPositions);
   Print(" Poll:      every ", InpPollSeconds, "s");
   Print("=================================");

   if(!SymbolSelect(InpSymbol, true))
   {
      Print("ERROR: Symbol ", InpSymbol, " not found in Market Watch. Check broker symbol name (e.g. XAUUSDm, GOLD).");
      return INIT_FAILED;
   }

   // Trigger an immediate poll on init
   PollAndTrade();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("AURUM EA stopped.");
}

void OnTimer()
{
   PollAndTrade();
}

void OnTick()
{
   ManageOpenPositions();
}

//+------------------------------------------------------------------+
//| Poll AURUM API and execute new signals                           |
//+------------------------------------------------------------------+
void PollAndTrade()
{
   last_poll_time = TimeCurrent();

   if(CountMyPositions() >= InpMaxPositions)
   {
      // At max positions — skip
      return;
   }

   string url = InpApiUrl + "/api/ea/signal?interval=" + InpInterval + "&strength=" + InpStrength;
   if(last_signal_id != "")
      url += "&last_id=" + last_signal_id;

   char post_data[];
   char result[];
   string result_headers;
   ResetLastError();
   int response_code = WebRequest("GET", url, NULL, NULL, 10000, post_data, 0, result, result_headers);

   if(response_code == -1)
   {
      int err = GetLastError();
      Print("WebRequest failed (err=", err, "). Did you whitelist ", InpApiUrl,
            " in Tools -> Options -> Expert Advisors -> Allow WebRequest?");
      return;
   }
   if(response_code != 200)
   {
      Print("WebRequest returned HTTP ", response_code);
      return;
   }

   string json = CharArrayToString(result, 0, -1, CP_UTF8);

   if(StringFind(json, "\"locked\":true") >= 0)
   {
      static datetime last_lock_log = 0;
      if(TimeCurrent() - last_lock_log > 900)
      {
         Print("AURUM daily loss limit hit — no new trades today: ", JsonStr(json, "reason"));
         last_lock_log = TimeCurrent();
      }
      return;
   }

   if(StringFind(json, "\"has_signal\":true") < 0)
      return; // no new signal

   // Parse signal fields
   string sig_id    = JsonStr(json, "id");
   string action    = JsonStr(json, "action");
   double entry     = JsonNum(json, "entry");
   double sl        = JsonNum(json, "stop_loss");
   double tp1       = JsonNum(json, "tp1");
   double tp2       = JsonNum(json, "tp2");
   double tp3       = JsonNum(json, "tp3");
   int    confidence = (int)JsonNum(json, "confidence");
   string strength  = JsonStr(json, "strength");

   if(sig_id == "") return;
   if(action != "BUY" && action != "SELL") return;
   if(sig_id == last_signal_id) return;

   // De-dup against open positions (in case EA restarted)
   if(IsSignalAlreadyTraded(sig_id))
   {
      last_signal_id = sig_id;
      return;
   }

   last_signal_id = sig_id;

   double lot_size = CalcLotSize(entry, sl);
   if(lot_size <= 0)
   {
      Print("Lot size <= 0, skipping. entry=", entry, " sl=", sl);
      return;
   }

   if(InpSemiAuto)
   {
      string msg = StringFormat(
         "AURUM Signal\n\n"
         "%s %s\n"
         "Entry:  %.2f\n"
         "SL:     %.2f\n"
         "TP1:    %.2f\n"
         "TP2:    %.2f\n"
         "TP3:    %.2f\n\n"
         "Confidence: %d%%\n"
         "Strength:   %s\n"
         "Lot size:   %.2f (~%.1f%% risk)\n\n"
         "Place this trade?",
         action, InpSymbol, entry, sl, tp1, tp2, tp3,
         confidence, strength, lot_size, InpRiskPercent);
      int reply = MessageBox(msg, "AURUM EA · Confirm Trade", MB_YESNO | MB_ICONQUESTION);
      if(reply != IDYES)
      {
         Print("User declined trade for signal ", sig_id);
         return;
      }
   }

   // Place market order. Initial TP = TP3 (final target); scale-out logic handles TP1.
   double final_tp = (tp3 > 0) ? tp3 : (tp2 > 0 ? tp2 : tp1);
   string comment = StringFormat("AURUM|%s|TP1=%.2f|TP3=%.2f", sig_id, tp1, final_tp);
   if(StringLen(comment) > 31) comment = StringSubstr(comment, 0, 31);

   bool ok = false;
   if(action == "BUY")
      ok = trade.Buy(lot_size, InpSymbol, 0, sl, final_tp, comment);
   else
      ok = trade.Sell(lot_size, InpSymbol, 0, sl, final_tp, comment);

   if(ok)
   {
      ulong opened_ticket = trade.ResultOrder();
      double opened_price = trade.ResultPrice();
      Print("Order placed: ", action, " ", lot_size, " ", InpSymbol,
            " · ticket=", opened_ticket, " · signal=", sig_id);
      ReportToAurum("OPENED", sig_id, opened_ticket, action,
                    lot_size, opened_price, sl, final_tp, 0.0, "");
   }
   else
   {
      string err = trade.ResultRetcodeDescription();
      Print("Order FAILED: ", trade.ResultRetcode(), " - ", err, " · signal=", sig_id);
      ReportToAurum("ERROR", sig_id, 0, action, lot_size, 0, sl, final_tp, 0.0, err);
   }
}

//+------------------------------------------------------------------+
//| Manage open positions: scale out at TP1, move SL to breakeven    |
//+------------------------------------------------------------------+
void ManageOpenPositions()
{
   if(!InpUseScaleOut) return;
   int point_buffer = 10; // small tolerance

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      if(PositionGetString(POSITION_SYMBOL) != InpSymbol) continue;

      string comment = PositionGetString(POSITION_COMMENT);
      if(StringFind(comment, "AURUM") < 0) continue;
      if(StringFind(comment, "TP1=") < 0) continue;

      string pos_sig_id = ExtractSignalId(comment);
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp1   = ParseCommentNum(comment, "TP1=");
      if(tp1 <= 0) continue;

      // Detect "already scaled" by checking if SL is at/past entry (breakeven)
      bool already_scaled = false;
      long ptype = PositionGetInteger(POSITION_TYPE);
      double point = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);
      if(ptype == POSITION_TYPE_BUY  && sl >= entry - point * point_buffer) already_scaled = true;
      if(ptype == POSITION_TYPE_SELL && sl <= entry + point * point_buffer) already_scaled = true;
      if(already_scaled) continue;

      // Check current price vs TP1
      double cur_price = (ptype == POSITION_TYPE_BUY)
                        ? SymbolInfoDouble(InpSymbol, SYMBOL_BID)
                        : SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
      bool tp1_hit = false;
      if(ptype == POSITION_TYPE_BUY  && cur_price >= tp1 - point * point_buffer) tp1_hit = true;
      if(ptype == POSITION_TYPE_SELL && cur_price <= tp1 + point * point_buffer) tp1_hit = true;
      if(!tp1_hit) continue;

      // Scale out
      double cur_vol = PositionGetDouble(POSITION_VOLUME);
      double close_vol = NormalizeVolume(cur_vol * (InpScaleOutPct / 100.0));
      double remaining = cur_vol - close_vol;
      double vol_min = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MIN);
      double current_tp = PositionGetDouble(POSITION_TP);
      if(close_vol >= vol_min && remaining >= vol_min)
      {
         if(trade.PositionClosePartial(ticket, close_vol))
         {
            Print("Scaled out ", close_vol, " lots at TP1 on ticket ", ticket);
            double locked = (ptype == POSITION_TYPE_BUY) ? (tp1 - entry) : (entry - tp1);
            double tick_value = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE);
            double tick_size  = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE);
            double profit_est = (tick_size > 0) ? (locked / tick_size) * tick_value * close_vol : 0;
            string side = (ptype == POSITION_TYPE_BUY) ? "BUY" : "SELL";
            ReportToAurum("SCALED_OUT", pos_sig_id, ticket, side, close_vol, tp1, sl, current_tp, profit_est, "");
         }
      }

      // Move SL to entry (breakeven). Keep current TP (which is TP3).
      if(trade.PositionModify(ticket, entry, current_tp))
      {
         Print("SL moved to breakeven on ticket ", ticket);
         string side = (ptype == POSITION_TYPE_BUY) ? "BUY" : "SELL";
         ReportToAurum("MOVED_BE", pos_sig_id, ticket, side, 0, entry, entry, current_tp, 0, "");
      }
   }
}

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
double CalcLotSize(double entry, double sl)
{
   if(InpFixedLot > 0) return NormalizeVolume(InpFixedLot);

   double balance      = AccountInfoDouble(ACCOUNT_BALANCE);
   double risk_amount  = balance * (InpRiskPercent / 100.0);
   double tick_value   = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size    = SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE);
   double sl_distance  = MathAbs(entry - sl);
   if(tick_size <= 0 || sl_distance <= 0 || tick_value <= 0) return 0;

   double loss_per_lot = (sl_distance / tick_size) * tick_value;
   if(loss_per_lot <= 0) return 0;

   double lot = risk_amount / loss_per_lot;
   return NormalizeVolume(lot);
}

double NormalizeVolume(double v)
{
   double v_min  = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MIN);
   double v_max  = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MAX);
   double v_step = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_STEP);
   if(v_step <= 0) v_step = 0.01;
   v = MathFloor(v / v_step) * v_step;
   v = MathMax(v_min, MathMin(v_max, v));
   return NormalizeDouble(v, 2);
}

int CountMyPositions()
{
   int total = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(PositionSelectByTicket(t))
      {
         if(PositionGetInteger(POSITION_MAGIC) == InpMagicNumber &&
            PositionGetString(POSITION_SYMBOL) == InpSymbol)
            total++;
      }
   }
   return total;
}

bool IsSignalAlreadyTraded(string sig_id)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(PositionSelectByTicket(t))
      {
         if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
         string c = PositionGetString(POSITION_COMMENT);
         if(StringFind(c, sig_id) >= 0) return true;
      }
   }
   return false;
}

string JsonStr(string json, string key)
{
   string needle = "\"" + key + "\":\"";
   int start = StringFind(json, needle);
   if(start < 0) return "";
   start += StringLen(needle);
   int end = StringFind(json, "\"", start);
   if(end < 0) return "";
   return StringSubstr(json, start, end - start);
}

double JsonNum(string json, string key)
{
   string needle = "\"" + key + "\":";
   int start = StringFind(json, needle);
   if(start < 0) return 0;
   start += StringLen(needle);
   int comma = StringFind(json, ",", start);
   int brace = StringFind(json, "}", start);
   int end;
   if(comma < 0) end = brace;
   else if(brace < 0) end = comma;
   else end = (comma < brace) ? comma : brace;
   if(end < 0) return 0;
   string num_str = StringSubstr(json, start, end - start);
   StringTrimLeft(num_str);
   StringTrimRight(num_str);
   if(num_str == "null" || num_str == "") return 0;
   return StringToDouble(num_str);
}

double ParseCommentNum(string comment, string tag)
{
   int pos = StringFind(comment, tag);
   if(pos < 0) return 0;
   string rest = StringSubstr(comment, pos + StringLen(tag));
   int sep = StringFind(rest, "|");
   if(sep >= 0) rest = StringSubstr(rest, 0, sep);
   return StringToDouble(rest);
}

string ExtractSignalId(string comment)
{
   int p1 = StringFind(comment, "AURUM|");
   if(p1 < 0) return "";
   string rest = StringSubstr(comment, p1 + 6);
   int p2 = StringFind(rest, "|");
   if(p2 > 0) return StringSubstr(rest, 0, p2);
   return rest;
}

//+------------------------------------------------------------------+
//| Report event to AURUM backend (which forwards to Telegram)       |
//+------------------------------------------------------------------+
void ReportToAurum(string event_type, string sig_id, ulong ticket,
                   string action, double lot, double price,
                   double sl, double tp, double profit, string note)
{
   if(!InpReportToAurum) return;
   if(InpApiUrl == "") return;

   string url = InpApiUrl + "/api/ea/event";
   string body = StringFormat(
      "{\"event\":\"%s\",\"signal_id\":\"%s\",\"ticket\":%d,\"symbol\":\"%s\",\"action\":\"%s\",\"lot\":%.2f,\"price\":%.2f,\"sl\":%.2f,\"tp\":%.2f,\"profit\":%.2f,\"note\":\"%s\"}",
      event_type, sig_id, (int)ticket, InpSymbol, action, lot, price, sl, tp, profit, note);

   char post[];
   StringToCharArray(body, post, 0, StringLen(body), CP_UTF8);
   // Trim trailing null
   int len = ArraySize(post);
   if(len > 0 && post[len - 1] == 0)
      ArrayResize(post, len - 1);

   char result[];
   string headers;
   string req_headers = "Content-Type: application/json\r\n";
   ResetLastError();
   int code = WebRequest("POST", url, req_headers, 10000, post, result, headers);
   if(code != 200)
      Print("ReportToAurum (", event_type, ") failed: HTTP ", code, " err=", GetLastError());
}

//+------------------------------------------------------------------+
//| OnTradeTransaction: detect position closures and report P/L     |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;

   long magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
   if(magic != InpMagicNumber) return;

   long entry_type = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry_type != DEAL_ENTRY_OUT) return; // only full/partial exits

   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
                 + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   double price  = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
   ulong pos_id  = HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
   double vol    = HistoryDealGetDouble(trans.deal, DEAL_VOLUME);

   // Skip partial closes (those are SCALED_OUT, already reported)
   bool is_full_close = !PositionSelectByTicket(pos_id);
   if(!is_full_close) return;

   string comment = HistoryDealGetString(trans.deal, DEAL_COMMENT);
   string sig_id = "";
   int p1 = StringFind(comment, "AURUM|");
   if(p1 >= 0)
   {
      string rest = StringSubstr(comment, p1 + 6);
      int p2 = StringFind(rest, "|");
      sig_id = (p2 > 0) ? StringSubstr(rest, 0, p2) : rest;
   }

   ReportToAurum("CLOSED", sig_id, pos_id, "", vol, price, 0, 0, profit, "");
}
//+------------------------------------------------------------------+
