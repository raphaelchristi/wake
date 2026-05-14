import Link from "next/link";
import adapters from "../../data/adapters.json";

export default function CatalogIndex() {
  return (
    <div>
      <h2>Listed adapters ({adapters.adapters.length})</h2>
      <table className="adapter-table">
        <thead>
          <tr>
            <th>Adapter</th>
            <th>Framework</th>
            <th>Conformance</th>
            <th>Last verified</th>
          </tr>
        </thead>
        <tbody>
          {adapters.adapters.map((a) => (
            <tr key={a.slug}>
              <td>
                <Link href={`/adapters/${a.slug}/`}>
                  <strong>{a.name}</strong>
                </Link>{" "}
                <span className="version">v{a.version}</span>
              </td>
              <td>{a.framework}</td>
              <td>
                <span className={`badge badge-score-${a.conformance_score === a.conformance_max ? "full" : "partial"}`}>
                  {a.conformance_score}/{a.conformance_max}
                </span>
              </td>
              <td>{a.last_verified}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <section className="claim-cta">
        <h3>Claim conformance for your adapter</h3>
        <p>
          Maintain a HarnessAdapter implementation and want to list it here? Copy{" "}
          <a href="https://github.com/raphaelchristi/wake/tree/main/templates/adapter-claim">
            templates/adapter-claim/
          </a>{" "}
          into your repo, run the workflow, and open a PR that adds your entry to{" "}
          <code>catalog/data/adapters.json</code>.
        </p>
      </section>
    </div>
  );
}
