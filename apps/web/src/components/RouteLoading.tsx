/** A restrained skeleton that preserves the existing visual language. */
export function RouteLoading() {
  return (
    <div className="route-loading-overlay">
      <div className="route-loading" role="status" aria-live="polite">
        <span className="sr-only">页面加载中</span>
        <div className="route-loading-heading route-loading-shimmer" />
        <div className="route-loading-subtitle route-loading-shimmer" />
        <div className="route-loading-tabs route-loading-shimmer" />
        <div className="route-loading-cards" aria-hidden="true">
          <div className="route-loading-card route-loading-shimmer" />
          <div className="route-loading-card route-loading-shimmer" />
          <div className="route-loading-card route-loading-shimmer" />
        </div>
        <div className="route-loading-panel route-loading-shimmer" aria-hidden="true" />
      </div>
    </div>
  );
}
