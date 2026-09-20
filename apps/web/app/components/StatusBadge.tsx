interface StatusBadgeProps {
  status: "live" | "stub";
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-badge--${status}`}>
      {status === "live" ? "Live" : "Not wired yet"}
    </span>
  );
}
