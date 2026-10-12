const RESULTS_VERSION = "4cd35fca808c";
const EMBEDDED_CSV = {
  "assets/data/full_1534_baseline_results.csv": String.raw`Model,ClickHouse,Doris,Drill,Druid,DuckDB,Hive,MySQL,Oracle,PostgreSQL,Presto,Spark,SQLite,StarRocks,T-SQL,Teradata,Trino,Avg.,Avg. N
GPT-3.5-Turbo,35.14,38.40,29.20,22.75,37.16,36.18,40.87,32.59,36.51,36.38,39.44,41.13,39.24,37.74,23.92,35.92,35.16,16
GPT-5-mini,51.63,49.93,48.89,37.81,52.87,54.11,54.37,47.46,51.43,51.11,53.06,52.54,51.96,53.91,35.92,49.09,49.76,16
GPT-5.1-codex,52.74,50.07,48.17,38.27,53.19,55.54,55.02,47.91,52.48,52.48,53.78,53.91,52.48,54.76,35.14,50.78,50.42,16
Gemini-2.5-Pro,54.04,51.76,50.85,37.42,56.19,59.32,57.82,26.14,53.59,57.95,56.65,59.78,54.43,55.61,38.40,55.61,51.60,16
Claude-4.5-Sonnet,56.84,52.80,52.28,39.90,55.35,59.65,58.60,49.61,55.08,58.21,56.19,59.97,56.06,56.26,37.81,56.13,53.80,16
Qwen3-1.7B,33.90,35.01,27.51,18.71,35.20,36.77,35.79,29.20,32.99,32.46,35.27,35.40,36.31,32.59,22.49,34.16,32.11,16
Qwen3-4B,43.09,44.52,41.79,26.60,44.33,46.81,46.68,37.16,42.83,41.79,43.94,47.07,45.57,46.48,29.66,41.53,41.86,16
Qwen3-8B,46.61,46.22,44.20,31.36,47.07,44.92,50.26,40.61,46.41,43.02,48.44,49.15,47.59,48.63,29.14,44.26,44.24,16
Qwen3-32B,49.80,47.26,46.61,33.90,50.00,52.02,52.09,44.20,48.57,47.85,49.28,53.46,50.59,51.76,32.33,46.68,47.27,16
Llama-3-8B-Inst,20.80,23.99,18.45,16.56,22.29,22.29,22.10,18.32,22.49,22.23,23.66,23.73,24.19,21.19,15.45,22.75,21.28,16
Llama-3-70B-Inst,40.22,40.16,37.87,26.92,41.79,42.70,43.81,35.14,40.22,38.07,42.96,42.31,42.63,40.61,26.47,39.11,38.81,16
DeepSeek-Coder-16B,32.53,31.10,32.20,21.38,32.86,34.94,36.64,28.23,31.94,12.84,34.42,35.14,34.88,31.75,20.01,32.59,30.22,16
DeepSeek-v4-flash,48.11,46.94,46.35,34.29,49.09,52.87,52.67,43.22,48.57,49.09,51.69,53.46,50.26,51.50,30.96,47.65,47.29,16`,
  "assets/data/clean_256_baseline_results.csv": String.raw`Model,ClickHouse,Doris,Drill,Druid,DuckDB,Hive,MySQL,Oracle,PostgreSQL,Presto,Spark,SQLite,StarRocks,T-SQL,Teradata,Trino,Avg.,Avg. N
GPT-3.5-Turbo,25.39,29.69,19.92,13.28,28.12,27.34,31.64,21.48,28.91,24.22,30.86,32.42,32.42,28.52,14.06,25.78,25.88,16
GPT-5-mini,51.17,49.22,46.88,32.03,55.08,56.64,56.25,48.05,52.34,49.22,53.52,54.30,50.78,55.47,31.64,49.22,49.49,16
GPT-5.1-codex,52.34,50.39,48.44,30.08,51.17,56.25,56.25,45.31,54.69,50.78,54.69,55.47,51.95,55.08,26.95,52.34,49.51,16
Gemini-2.5-Pro,51.95,50.00,47.27,32.03,55.08,57.81,55.86,23.05,54.30,55.86,55.08,59.38,51.95,52.34,33.98,54.30,49.39,16
Claude-4.5-Sonnet,57.81,49.61,51.56,34.77,53.91,59.77,57.03,46.88,56.64,58.20,54.69,58.98,55.47,57.03,32.42,55.47,52.51,16
Qwen3-1.7B,26.95,24.22,21.88,7.81,30.08,29.30,29.69,21.09,22.27,26.17,30.86,31.25,30.47,21.09,12.50,27.73,24.58,16
Qwen3-4B,38.28,41.80,34.38,17.97,40.62,44.53,44.53,34.38,37.50,35.16,42.19,45.31,44.14,41.80,20.31,35.16,37.38,16
Qwen3-8B,41.41,40.23,39.84,23.05,40.23,42.19,48.05,34.77,44.53,38.67,46.48,44.53,44.92,46.88,19.14,36.33,39.45,16
Qwen3-32B,44.14,43.36,43.75,26.17,47.27,53.91,50.00,40.62,42.58,42.97,47.27,50.00,48.44,51.56,25.39,41.80,43.70,16
Llama-3-8B-Inst,16.41,17.58,11.33,7.81,15.23,14.06,15.23,12.50,14.84,13.67,16.41,16.02,18.75,15.23,8.59,16.02,14.36,16
Llama-3-70B-Inst,35.55,36.72,28.52,17.19,38.28,39.84,36.72,29.69,33.98,29.69,40.62,36.72,42.19,35.55,17.58,32.81,33.23,16
DeepSeek-Coder-16B,24.61,20.70,23.83,9.77,25.39,30.47,30.86,18.75,25.00,9.77,26.95,27.34,29.30,25.39,8.59,20.31,22.31,16
DeepSeek-v4-flash,42.58,42.97,40.62,24.22,46.88,52.73,51.17,41.41,45.31,44.53,51.17,52.34,49.61,49.61,23.05,42.97,43.82,16`,
};

async function loadLeaderboard() {
  await renderLeaderboard("leaderboard-full", "assets/data/full_1534_baseline_results.csv", "UniQL-Full");
  await renderLeaderboard("leaderboard-clean", "assets/data/clean_256_baseline_results.csv", "UniQL-Minidev");
}

async function renderLeaderboard(tableId, csvPath, trackName) {
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
      if (header === "Model") th.classList.add("model-head");
      headRow.appendChild(th);
    }
    tableHead.appendChild(headRow);

    tableBody.innerHTML = "";
    selected.forEach((row, rank) => {
      const tr = document.createElement("tr");
      if (rank < 3) tr.classList.add(`rank-${rank + 1}`);
      const rowHeaders = ["Rank", ...headers];
      rowHeaders.forEach((header, index) => {
        const cell = document.createElement(index === 1 ? "th" : "td");
        if (header === "Avg.") cell.classList.add("avg-cell");
        if (header === "Rank") cell.classList.add("rank-cell");
        if (header === "Model") cell.classList.add("model-cell");
        fillLeaderboardCell(cell, row, header, rank, trackName);
        tr.appendChild(cell);
      });
      tableBody.appendChild(tr);
    });
  } catch (error) {
    tableBody.innerHTML = `<tr><td>Could not load leaderboard data.</td></tr>`;
  }
}

function fillLeaderboardCell(cell, row, header, rank, trackName) {
  if (header === "Rank") {
    cell.textContent = String(rank + 1);
    return;
  }

  const main = document.createElement("span");
  main.className = "cell-main";
  main.textContent = row[header] || "--";
  cell.appendChild(main);

  const detail = document.createElement("span");
  detail.className = "cell-detail";
  detail.textContent = getLeaderboardCellDetail(row, header, trackName) || "\u00a0";
  cell.appendChild(detail);
}

function getLeaderboardCellDetail(row, header, trackName) {
  // Keep this hook for future per-cell notes, such as test date, metric, or submitted dialect count.
  return "";
}

async function loadCsvText(csvPath) {
  try {
    const response = await fetch(`${csvPath}?v=${RESULTS_VERSION}`, { cache: "no-cache" });
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

function setupTabs() {
  const tabs = document.querySelectorAll(".tab[data-target]");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.getAttribute("data-target");
      tabs.forEach((item) => item.classList.toggle("active", item === tab));
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === target);
      });
    });
  });
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
setupTabs();
