// One record per model/system, track and dialect. See docs/README.md for the format.
const DIALECT_SUBMISSIONS = [
  {
    id: "schemagate-gemini38-oracle-20261113",
    model: "schemagate + Gemini 3.8 Flash",
    model_url: "https://ashishsinha1602.github.io/schemagate/",
    track: "UniQL-1534",
    dialect: "Oracle",
    reference_version: "audited-20261112",
    gold_commit: "dec96c9dc15e1e6a7c075ba6771e59de86a79b43",
    evaluator_commit: "dec96c9dc15e1e6a7c075ba6771e59de86a79b43",
    correct: 996,
    total: 1534,
    submitted_date: "2026-11-18",
    inference_setup: "Schema retrieval; Oracle error feedback repair",
    database_error_feedback: true,
    gold_correctness_feedback: false,
    source_url: "https://github.com/JerryGao818/UniQL/issues/2#issuecomment-6966196358",
    results_url: "https://github.com/ashishsinha1602/schemagate/tree/41b005ee18ff68c0fbd1d3193d6569a00cfb40c0/benchmarks/results/uniql_oracle",
    difficulty: {
      simple: { correct: 646, total: 925 },
      moderate: { correct: 268, total: 464 },
      challenging: { correct: 82, total: 145 },
    },
  },
];
