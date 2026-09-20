interface SourceCardProps {
  index: number;
  header: string;
  excerpt: string;
  relevance: number;
}

export function SourceCard({ index, header, excerpt, relevance }: SourceCardProps) {
  const confidenceClass = relevance >= 0.7 ? "confidence--high" : "confidence--mid";
  return (
    <div className="source-card">
      <div className="source-num">{index}</div>
      <div className="source-body">
        <p className="source-title">{header}</p>
        <p className="source-excerpt">{excerpt}</p>
      </div>
      <div className={`confidence ${confidenceClass}`}>{relevance.toFixed(2)}</div>
    </div>
  );
}
