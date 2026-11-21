import { useEffect, useState } from "react";
import { fetchNews } from "@/lib/api";
import { Newspaper, ExternalLink, Loader2 } from "lucide-react";

function timeAgo(dateStr) {
    if (!dateStr) return "";
    const d = new Date(dateStr);
    const s = Math.floor((Date.now() - d.getTime()) / 1000);
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h`;
    return `${Math.floor(s / 86400)}d`;
}

export default function NewsFeed() {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let alive = true;
        fetchNews(12)
            .then((d) => { if (alive) setItems(d.items || []); })
            .catch(() => {})
            .finally(() => { if (alive) setLoading(false); });
        return () => { alive = false; };
    }, []);

    return (
        <div className="bg-[#121212] border border-[#262626] rounded-sm" data-testid="news-feed">
            <div className="flex items-center gap-2 px-4 py-2 border-b border-[#262626]">
                <Newspaper className="w-3.5 h-3.5 text-[#D4AF37]" />
                <span className="text-[10px] font-mono text-gray-500 uppercase tracking-[0.2em]">Gold Market News</span>
            </div>
            <div className="max-h-[600px] overflow-y-auto">
                {loading && (
                    <div className="p-6 text-center"><Loader2 className="w-4 h-4 mx-auto animate-spin text-[#D4AF37]" /></div>
                )}
                {!loading && items.length === 0 && (
                    <div className="p-4 text-xs font-mono text-gray-500">No news available.</div>
                )}
                {items.map((n, i) => (
                    <a
                        key={i}
                        href={n.link}
                        target="_blank"
                        rel="noreferrer"
                        data-testid={`news-item-${i}`}
                        className="block px-4 py-3 border-b border-[#262626]/60 hover:bg-[#1A1A1A] transition-colors group"
                    >
                        <div className="flex items-start gap-2">
                            <div className="flex-1">
                                <div className="text-sm text-white leading-snug group-hover:text-[#D4AF37] transition-colors">
                                    {n.title}
                                </div>
                                <div className="mt-1 flex items-center gap-2 text-[10px] font-mono text-gray-500 uppercase tracking-[0.1em]">
                                    <span>{timeAgo(n.published)} ago</span>
                                </div>
                            </div>
                            <ExternalLink className="w-3 h-3 text-gray-600 group-hover:text-[#D4AF37] mt-1 shrink-0" />
                        </div>
                    </a>
                ))}
            </div>
        </div>
    );
}
