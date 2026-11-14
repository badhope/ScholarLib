import { createFileRoute } from "@tanstack/react-router";
import { IssuePageContent } from "./archive_.$issue";

export const Route = createFileRoute("/issues/$volume/$issue")({
  component: CanonicalIssuePage,
});

function CanonicalIssuePage() {
  const { volume, issue } = Route.useParams();
  return <IssuePageContent issueParam={issue} volumeParam={volume} />;
}
