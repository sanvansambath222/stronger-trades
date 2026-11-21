import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API, timeout: 30000 });

export const fetchQuote = () => api.get("/market/quote").then(r => r.data);
export const fetchCandles = (interval, size = 150) =>
    api.get("/market/candles", { params: { interval, size } }).then(r => r.data);
export const fetchIndicators = (interval) =>
    api.get("/analysis/indicators", { params: { interval } }).then(r => r.data);
export const fetchAISignal = (interval, engine = "rule", autoUpgrade = false, newsBlackout = false, blackoutWindow = 15, withRiskTeam = false, runId = null) =>
    api.get("/analysis/ai", {
        params: {
            interval,
            engine,
            auto_upgrade: autoUpgrade,
            news_blackout: newsBlackout,
            blackout_window: blackoutWindow,
            with_risk_team: withRiskTeam,
            run_id: runId,
        },
        // Council+Risk = 4 sequential stages (each capped at 45s); Council = 2 stages; Deep AI = 1 parallel stage
        timeout: engine === "council" ? (withRiskTeam ? 240000 : 130000) : 90000,
    }).then(r => {
        if (r.data && r.data.detail && !r.data.action) throw new Error(r.data.detail);
        return r.data;
    });
export const fetchAIModels = () => api.get("/ai/models").then(r => r.data);
export const fetchAISettings = () => api.get("/ai/settings").then(r => r.data);
export const saveAISettings = (payload) => api.put("/ai/settings", payload).then(r => r.data);
export const fetchAIProgress = (runId) => api.get(`/ai/progress/${runId}`).then(r => r.data);
export const fetchCalendarEvents = (params = {}) =>
    api.get("/calendar/events", { params }).then(r => r.data);
export const fetchBlackoutStatus = (windowMinutes = 15) =>
    api.get("/calendar/blackout", { params: { window_minutes: windowMinutes } }).then(r => r.data);
export const fetchSignalHistory = (limit = 10) =>
    api.get("/signals/history", { params: { limit } }).then(r => r.data);
export const fetchNews = (limit = 12) =>
    api.get("/news", { params: { limit } }).then(r => r.data);
export const fetchTelegramConfig = () => api.get("/telegram/config").then(r => r.data);
export const updateTelegramConfig = (payload) => api.post("/telegram/config", payload).then(r => r.data);
export const sendTelegramTest = () => api.post("/telegram/test").then(r => r.data);
export const sendEAToTelegram = () => api.post("/telegram/send-ea").then(r => r.data);
