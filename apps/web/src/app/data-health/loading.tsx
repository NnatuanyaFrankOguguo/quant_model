/**
 * The loading state, which DESIGN.md §7 requires a page to handle explicitly.
 *
 * It matters more here than elsewhere: this page answers "is the data fresh?", and a
 * blank screen while it is thinking could be read as "nothing is running".
 */
export default function LoadingDataHealth() {
  return (
    <>
      <h1>Data health</h1>
      <div className="notice">
        <h3>Asking the system about itself</h3>
        <p>
          Reading the run log for every loading job in the window. Until that comes back,
          this page knows nothing about how fresh the data is — which is not the same as
          knowing that it is stale.
        </p>
      </div>
    </>
  );
}
