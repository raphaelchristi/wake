/**
 * Next.js segment loading UI. Rendered while the server component / data
 * dependency for the replay page is resolving.
 */
export default function ReplayLoading(): React.ReactElement {
  return (
    <div
      className="flex h-full items-center justify-center p-12 text-sm text-slate-500"
      data-testid="replay-loading"
    >
      Loading replay…
    </div>
  );
}
