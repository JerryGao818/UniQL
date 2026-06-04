const EMBEDDED_CSV = {
  "assets/data/full_1534_baseline_results.csv": String.raw`Model,ClickHouse,Doris,Drill,Druid,DuckDB,Hive,MySQL,Oracle,PostgreSQL,Presto,Spark,SQLite,StarRocks,T-SQL,Teradata,Trino,Avg.,Avg. N
GPT-3.5-Turbo,35.14,38.33,29.20,22.75,37.09,36.18,40.81,49.35,36.44,36.31,39.37,41.13,39.18,37.74,23.86,35.85,36.17,16
GPT-5-mini,51.56,49.80,48.83,37.74,52.74,54.04,54.30,60.56,51.37,50.98,52.93,52.48,51.89,53.85,35.85,49.02,50.50,16
GPT-5.1-codex,52.61,49.93,48.11,38.20,52.93,55.48,54.89,49.67,52.35,52.41,53.65,53.78,52.41,54.63,35.07,50.72,50.43,16
Gemini-2.5-Pro,53.98,51.76,50.85,37.42,56.19,59.32,57.82,34.29,53.59,57.89,56.65,59.78,54.43,55.61,38.40,55.61,52.10,16
Claude-4.5-Sonnet,56.84,52.74,52.28,39.90,55.28,59.58,58.54,63.75,54.95,58.08,56.13,59.84,56.06,56.26,37.74,56.06,54.63,16
Qwen3-1.7B,33.90,35.07,27.57,18.71,35.27,36.70,35.85,43.48,32.92,32.46,35.27,35.40,36.31,32.66,22.43,34.16,33.01,16
Qwen3-4B,43.02,44.52,41.72,26.53,44.26,46.74,46.61,44.92,42.70,41.72,43.94,46.94,45.50,46.41,29.60,41.46,42.29,16
Qwen3-8B,46.54,46.15,44.13,31.29,47.00,44.85,50.20,51.11,46.35,32.99,47.46,49.09,47.46,48.57,29.34,44.20,44.17,16
Qwen3-32B,49.74,47.20,46.54,33.83,49.93,51.96,52.02,53.06,48.50,47.78,49.22,53.39,50.52,51.69,32.27,46.61,47.77,16
Llama-3-8B-Inst,20.80,23.99,18.45,16.56,22.29,22.23,22.03,31.23,22.43,22.23,23.34,23.60,24.12,21.12,15.45,22.75,22.04,16
Llama-3-70B-Inst,40.16,40.09,37.74,26.92,41.72,42.63,43.74,51.56,40.16,38.01,42.89,42.24,42.57,40.61,26.47,39.05,39.78,16
DeepSeek-Coder-16B,32.46,31.10,32.07,21.38,32.72,34.88,36.57,45.44,31.88,31.55,34.42,35.01,34.88,31.68,19.95,32.53,32.41,16
DeepSeek-v4-flash,48.04,46.94,46.28,34.22,49.02,52.80,52.54,57.50,48.50,49.02,51.56,53.46,50.20,51.43,30.90,47.59,48.12,16`,
  "assets/data/clean_256_baseline_results.csv": String.raw`Model,ClickHouse,Doris,Drill,Druid,DuckDB,Hive,MySQL,Oracle,PostgreSQL,Presto,Spark,SQLite,StarRocks,T-SQL,Teradata,Trino,Avg.,Avg. N
GPT-3.5-Turbo,25.39,29.69,19.92,13.28,28.12,27.34,31.64,42.58,28.91,24.22,30.86,32.42,32.42,28.52,14.06,25.78,27.20,16
GPT-5-mini,51.17,49.22,46.88,32.03,55.08,56.64,56.25,62.89,52.34,49.22,53.52,54.30,50.78,55.47,31.64,49.22,50.42,16
GPT-5.1-codex,52.34,50.39,48.44,30.08,51.17,56.25,56.25,46.48,54.69,50.78,54.69,55.47,51.95,55.08,26.95,52.34,49.58,16
Gemini-2.5-Pro,51.95,50.00,47.27,32.03,55.08,57.81,55.86,34.77,54.30,55.86,55.08,59.38,51.95,52.34,33.98,54.30,50.12,16
Claude-4.5-Sonnet,57.81,49.61,51.56,34.77,53.91,59.77,57.03,62.50,56.64,58.20,54.69,58.98,55.47,57.03,32.42,55.47,53.49,16
Qwen3-1.7B,26.95,24.22,21.88,7.81,30.08,29.30,29.69,39.06,22.27,26.17,30.86,31.25,30.47,21.09,12.50,27.73,25.71,16
Qwen3-4B,38.28,41.80,34.38,17.97,40.62,44.53,44.53,47.66,37.50,35.16,42.19,45.31,44.14,41.80,20.31,35.16,38.21,16
Qwen3-8B,41.41,40.23,39.84,23.05,40.23,42.19,48.05,50.39,44.53,38.67,46.48,44.53,44.92,46.88,19.14,36.33,40.43,16
Qwen3-32B,44.14,43.36,43.75,26.17,47.27,53.91,50.00,52.34,42.58,42.97,47.27,50.00,48.44,51.56,25.39,41.80,44.43,16
Llama-3-8B-Inst,16.41,17.58,11.33,7.81,15.23,14.06,15.23,27.34,14.84,13.67,16.41,16.02,18.75,15.23,8.59,16.02,15.28,16
Llama-3-70B-Inst,35.55,36.72,28.52,17.19,38.28,39.84,36.72,46.88,33.98,29.69,40.62,36.72,42.19,35.55,17.58,32.81,34.30,16
DeepSeek-Coder-16B,24.61,20.70,23.83,9.77,25.39,30.47,30.86,41.02,25.00,9.77,26.95,27.34,29.30,25.39,8.59,20.31,23.71,16
DeepSeek-v4-flash,42.58,42.97,40.62,24.22,46.88,52.73,51.17,55.86,45.31,44.53,51.17,52.34,49.61,49.61,23.05,42.97,44.73,16`,
};

async function loadLeaderboard() {
  await renderLeaderboard("leaderboard-full", "assets/data/full_1534_baseline_results.csv");
  await renderLeaderboard("leaderboard-clean", "assets/data/clean_256_baseline_results.csv");
}

async function renderLeaderboard(tableId, csvPath) {
  const table = document.querySelector(`#${tableId}`);
  const tableHead = table?.querySelector("thead");
  const tableBody = table?.querySelector("tbody");
  if (!table || !tableHead || !tableBody) return;

  try {
    const text = await loadCsvText(csvPath);
    const rows = parseCsv(text);
    const headers = [
      "Model",
      "Avg.",
      "ClickHouse",
      "Doris",
      "Drill",
      "Druid",
      "DuckDB",
      "Hive",
      "MySQL",
      "Oracle",
      "PostgreSQL",
      "Presto",
      "Spark",
      "SQLite",
      "StarRocks",
      "T-SQL",
      "Teradata",
      "Trino",
    ];
    const selected = rows
      .filter((row) => row.Model)
      .sort((a, b) => Number.parseFloat(b["Avg."]) - Number.parseFloat(a["Avg."]));

    tableHead.innerHTML = "";
    const headRow = document.createElement("tr");
    for (const header of ["Rank", ...headers]) {
      const th = document.createElement("th");
      th.textContent = header;
      if (header === "Avg.") th.classList.add("avg-head");
      if (header === "Rank") th.classList.add("rank-head");
      headRow.appendChild(th);
    }
    tableHead.appendChild(headRow);

    tableBody.innerHTML = "";
    selected.forEach((row, rank) => {
      const tr = document.createElement("tr");
      if (rank < 3) tr.classList.add(`rank-${rank + 1}`);
      const rowHeaders = ["Rank", ...headers];
      rowHeaders.forEach((header, index) => {
        const value = header === "Rank" ? String(rank + 1) : row[header] || "--";
        const cell = document.createElement(index === 1 ? "th" : "td");
        if (header === "Avg.") cell.classList.add("avg-cell");
        if (header === "Rank") cell.classList.add("rank-cell");
        cell.textContent = value || "--";
        tr.appendChild(cell);
      });
      tableBody.appendChild(tr);
    });
  } catch (error) {
    tableBody.innerHTML = `<tr><td>Could not load leaderboard data.</td></tr>`;
  }
}

async function loadCsvText(csvPath) {
  try {
    const response = await fetch(csvPath);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.text();
  } catch (error) {
    if (EMBEDDED_CSV[csvPath]) return EMBEDDED_CSV[csvPath];
    throw error;
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
