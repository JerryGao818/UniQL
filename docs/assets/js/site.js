async function loadLeaderboard() {
  const tableBody = document.querySelector("#leaderboard-table tbody");
  if (!tableBody) return;

  try {
    const response = await fetch("assets/data/clean_256_baseline_results.csv");
    const text = await response.text();
    const rows = parseCsv(text);
    const selected = rows
      .filter((row) => row.Model)
      .sort((a, b) => Number.parseFloat(b["Avg."]) - Number.parseFloat(a["Avg."]));

    tableBody.innerHTML = "";
    for (const row of selected) {
      const tr = document.createElement("tr");
      const cells = [
        row.Model,
        row["Avg."],
        row.SQLite,
        row.MySQL,
        row.PostgreSQL,
        row.Oracle,
        row.Hive,
        row.Trino,
        row.Teradata,
      ];
      for (const value of cells) {
        const cell = document.createElement(cells.indexOf(value) === 0 ? "th" : "td");
        cell.textContent = value || "--";
        tr.appendChild(cell);
      }
      tableBody.appendChild(tr);
    }
  } catch (error) {
    tableBody.innerHTML = `<tr><td colspan="9">Could not load leaderboard data.</td></tr>`;
  }
}

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = splitCsvLine(lines.shift());
  return lines.map((line) => {
    const values = splitCsvLine(line);
    const row = {};
    headers.forEach((header, index) => {
      row[header] = values[index] ?? "";
    });
    return row;
  });
}

function splitCsvLine(line) {
  const out = [];
  let current = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"') {
      if (quoted && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      out.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  out.push(current);
  return out;
}

function setupValidator() {
  const input = document.querySelector("#json-file");
  const output = document.querySelector("#validator-output");
  if (!input || !output) return;

  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      if (!Array.isArray(data)) {
        output.textContent = "Invalid: expected a JSON array.";
        return;
      }
      const missing = data.filter((row) => {
        const hasId = row.sql_idx !== undefined || row.question_id !== undefined;
        return !hasId || row.res === undefined;
      }).length;
      if (missing) {
        output.textContent = `Invalid: ${missing} rows are missing sql_idx/question_id or res.`;
        return;
      }
      const correct = data.filter((row) => Boolean(row.res)).length;
      const accuracy = data.length ? ((correct * 100) / data.length).toFixed(2) : "0.00";
      output.textContent = `Looks valid: ${data.length} rows, ${correct} correct, ${accuracy}% accuracy in this file.`;
    } catch (error) {
      output.textContent = `Invalid JSON: ${error.message}`;
    }
  });
}

function setupIssueLink() {
  const link = document.querySelector("#issue-link");
  if (!link) return;
  const repo = inferGitHubRepo();
  if (repo) {
    link.href = `https://github.com/${repo}/issues/new?template=leaderboard_submission.yml`;
  }
}

function setupRepoLinks() {
  const repo = inferGitHubRepo();
  for (const link of document.querySelectorAll("[data-repo-path]")) {
    const path = link.getAttribute("data-repo-path");
    if (repo) {
      link.href = `https://github.com/${repo}/tree/main/${path}`;
    } else {
      link.href = `../${path}`;
    }
  }
}

function inferGitHubRepo() {
  if (!window.location.hostname.endsWith("github.io")) return "";
  const owner = window.location.hostname.replace(".github.io", "");
  const repo = window.location.pathname.split("/").filter(Boolean)[0];
  return repo ? `${owner}/${repo}` : "";
}

loadLeaderboard();
setupValidator();
setupIssueLink();
setupRepoLinks();
