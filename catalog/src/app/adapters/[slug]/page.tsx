import { notFound } from "next/navigation";
import Link from "next/link";
import adapters from "../../../../data/adapters.json";

export function generateStaticParams() {
  return adapters.adapters.map((a) => ({ slug: a.slug }));
}

export default async function AdapterDetail({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const adapter = adapters.adapters.find((a) => a.slug === slug);
  if (!adapter) notFound();

  return (
    <article>
      <Link href="/">← Back to catalog</Link>
      <h2>
        {adapter.name}{" "}
        <span className="version">v{adapter.version}</span>
      </h2>
      <p className="description">{adapter.description}</p>
      <dl className="metadata">
        <dt>Framework</dt>
        <dd>{adapter.framework}</dd>
        <dt>Conformance</dt>
        <dd>
          <span className="badge badge-score-full">
            {adapter.conformance_score}/{adapter.conformance_max}
          </span>{" "}
          (verified {adapter.last_verified})
        </dd>
        <dt>Maintainers</dt>
        <dd>{adapter.maintainers.join(", ")}</dd>
        <dt>Homepage</dt>
        <dd>
          <a href={adapter.homepage} target="_blank" rel="noreferrer">
            {adapter.homepage}
          </a>
        </dd>
      </dl>
      <section>
        <h3>Embed badge</h3>
        <pre className="badge-snippet">
          {`[![Wake conformance](https://catalog.wake.dev/badge/${adapter.slug}.svg)](https://catalog.wake.dev/adapters/${adapter.slug}/)`}
        </pre>
      </section>
    </article>
  );
}
