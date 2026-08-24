window.DAGCERT_SAMPLE = {
  contract: {
    schema: "dagcert-contract/v2",
    workers: [
      {id: "interaction", concurrency: 8},
      {id: "planner", concurrency: 2},
      {id: "renderer", concurrency: 3}
    ],
    resources: [
      {id: "render-work", capacity: 24, initial: 6, unit: "prompts"},
      {id: "model-lag", capacity: 3, initial: 0, unit: "generations"},
      {id: "gpu", capacity: 3, initial: 0, unit: "slots"}
    ],
    tasks: [
      {id: "user.vote", worker: "interaction", input_type: "Vote", output_type: "Signal", depends_on: [], resources: {"model-lag": {produce: 1}}, timings: {
        feedback: {metric: "duration", upper_ms: 16, evidence: "measured"},
        cadence: {metric: "interval", upper_ms: 900, evidence: "assumed"}
      }},
      {id: "prompt.plan", worker: "planner", input_type: "Signal", output_type: "Prompt", depends_on: ["user.vote"], resources: {"model-lag": {consume: 1}, "render-work": {produce: 1}}, timings: {
        completion: {metric: "duration", upper_ms: 240, evidence: "measured"},
        freshness: {metric: "age", upper_ms: 1800, evidence: "measured"}
      }},
      {id: "image.render", worker: "renderer", input_type: "Prompt", output_type: "Image", depends_on: ["prompt.plan"], resources: {"render-work": {consume: 1}, gpu: {acquire: 1}}, timings: {
        completion: {metric: "duration", lower_ms: 680, upper_ms: 1400, evidence: "measured"},
        ready_gap: {metric: "wait", upper_ms: 40, evidence: "measured"}
      }}
    ]
  },
  evidence: [
    ["user.vote","feedback",[7.8,8.4,9.1,7.2,10.0,8.7,9.4,8.1]],
    ["user.vote","cadence",[880,840,860,810,895,825,875,850]],
    ["prompt.plan","completion",[128,142,151,137,160,146,139,154]],
    ["prompt.plan","freshness",[610,720,680,790,740,830,710,760]],
    ["image.render","completion",[892,940,1018,976,1102,934,1056,998]],
    ["image.render","ready_gap",[4,7,3,9,6,5,8,4]]
  ].flatMap(([task_id, caseName, values], series) =>
    values.map((value_ms, index) => ({
      task_id,
      case: caseName,
      value_ms,
      recorded_at: 1724000000 + series * 30 + index * 8,
      succeeded: true,
    })),
  ),
  certificate: {
    source_fingerprint: "39f6b7b517183c6d8b5e35dc256ad9607985c61f4ce7c40afe94c06f159c8a91",
    analysis: {
      passed: true,
      conditional: true,
      assumptions: ["timing:user.vote/cadence (interval) is assumed < 900ms"],
      structural_progress: {passed:true, claim:"every declared task has a feasible worker/resource path and finite completion evidence"}
    },
    checks: [{checker:"example.flow-bounds/v1", passed:true, facts:{claims:[
      "image.render remains supplied after warm-up",
      "declared tasks have no structural blocked state",
      "prompt.plan model lag remains at most 3 generations"
    ]}}]
  }
};
