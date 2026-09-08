import userNotice from "../../../docs/user_notice.md?raw";

type Block =
  | { type: "h1"; text: string }
  | { type: "h2"; text: string }
  | { type: "p"; text: string }
  | { type: "ol"; items: string[] }
  | { type: "code"; lines: string[] };

function cleanInline(text: string): string {
  return text.replace(/\*\*/g, "").replace(/`([^`]+)`/g, "$1");
}

function parseMarkdown(markdown: string): Block[] {
  const blocks: Block[] = [];
  const lines = markdown.split(/\r?\n/);
  let codeLines: string[] | null = null;

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      if (codeLines) {
        blocks.push({ type: "code", lines: codeLines });
        codeLines = null;
      } else {
        codeLines = [];
      }
      continue;
    }
    if (codeLines) {
      codeLines.push(line);
      continue;
    }
    if (!line.trim()) {
      continue;
    }
    if (line.startsWith("# ")) {
      blocks.push({ type: "h1", text: line.slice(2) });
      continue;
    }
    if (line.startsWith("## ")) {
      blocks.push({ type: "h2", text: cleanInline(line.slice(3)) });
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const items = [cleanInline(line.replace(/^\d+\.\s+/, ""))];
      while (index + 1 < lines.length && /^\d+\.\s+/.test(lines[index + 1].trimEnd())) {
        index += 1;
        items.push(cleanInline(lines[index].trimEnd().replace(/^\d+\.\s+/, "")));
      }
      blocks.push({ type: "ol", items });
      continue;
    }
    blocks.push({ type: "p", text: cleanInline(line) });
  }

  return blocks;
}

export default function TermsPage() {
  const blocks = parseMarkdown(userNotice);

  return (
    <main className="terms-page">
      <nav className="terms-topbar">
        <a href="/">返回</a>
      </nav>
      <article className="terms-document">
        {blocks.map((block, index) => {
          if (block.type === "h1") {
            return <h1 key={index}>{block.text}</h1>;
          }
          if (block.type === "h2") {
            return <h2 key={index}>{block.text}</h2>;
          }
          if (block.type === "ol") {
            return (
              <ol key={index}>
                {block.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ol>
            );
          }
          if (block.type === "code") {
            return (
              <pre key={index}>
                <code>{block.lines.join("\n")}</code>
              </pre>
            );
          }
          return <p key={index}>{block.text}</p>;
        })}
      </article>
    </main>
  );
}
