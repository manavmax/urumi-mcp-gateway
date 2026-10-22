/* RC: friendly panel for optional features that this deployment does not run
   (Helm flags provisioner.enabled / hostedServers.enabled off). Rendered
   INSTEAD of the page content - no API calls, no console errors. One line tells
   an admin how to enable the feature. Styles reuse the app's card system so it
   looks native in light and dark. */
import { Icon } from "./icons";

export function FeatureDisabled({
  title,
  icon,
  enableHint,
}: {
  title: string;
  icon: "store" | "server";
  enableHint: string;
}) {
  return (
    <main className="content">
      <div className="page-head">
        <div>
          <h1>{title}</h1>
        </div>
      </div>
      <section className="card feature-disabled" aria-live="polite">
        <span className="fd-icon" aria-hidden="true">
          <Icon name={icon} size={26} />
        </span>
        <div>
          <p className="fd-title">This feature is not enabled on this deployment</p>
          <p className="small muted">{enableHint}</p>
        </div>
      </section>
    </main>
  );
}
