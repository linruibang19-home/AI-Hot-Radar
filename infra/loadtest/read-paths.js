import http from "k6/http";
import { check, group, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";

const baseUrl = __ENV.BASE_URL || "http://host.docker.internal:3000";
const coreUrl = __ENV.CORE_URL || "http://host.docker.internal:8080";
const aiUrl = __ENV.AI_URL || "http://host.docker.internal:8000";
const profile = __ENV.PROFILE || "baseline";

const businessFailure = new Rate("business_failure");
const webLatency = new Trend("web_latency", true);
const coreLatency = new Trend("core_latency", true);
const aiControlLatency = new Trend("ai_control_latency", true);

const profiles = {
  smoke: [
    { duration: "5s", target: 2 },
    { duration: "5s", target: 0 },
  ],
  baseline: [
    { duration: "15s", target: 5 },
    { duration: "30s", target: 10 },
    { duration: "30s", target: 20 },
    { duration: "15s", target: 0 },
  ],
  // Low-risk verification for the live 2C4G host. It runs inside the Compose
  // network, never through the public domain, and only exercises GET routes.
  // This is intentionally not a capacity-seeking profile.
  "production-safe": [
    { duration: "10s", target: 1 },
    { duration: "20s", target: 2 },
    { duration: "20s", target: 5 },
    { duration: "10s", target: 0 },
  ],
};

export const options = {
  stages: profiles[profile] || profiles.baseline,
  discardResponseBodies: true,
  summaryTrendStats: ["avg", "med", "p(90)", "p(95)", "p(99)", "max"],
  thresholds: {
    http_req_failed: [
      { threshold: "rate<0.01", abortOnFail: true, delayAbortEval: "15s" },
    ],
    business_failure: [
      { threshold: "rate<0.01", abortOnFail: true, delayAbortEval: "15s" },
    ],
    http_req_duration: ["p(95)<1500"],
    web_latency: ["p(95)<1500"],
    core_latency: ["p(95)<750"],
    ai_control_latency: ["p(95)<750"],
  },
};

function verify(response, label) {
  const ok = check(response, {
    [`${label}: status 200`]: (r) => r.status === 200,
  });
  businessFailure.add(!ok);
}

export function setup() {
  const probes = [
    http.get(`${coreUrl}/health/ready`),
    http.get(`${aiUrl}/health/ready`),
    http.get(`${baseUrl}/topics`),
  ];
  probes.forEach((response, index) => verify(response, `setup-${index}`));
}

export default function () {
  group("core-api public reads", () => {
    const responses = http.batch([
      ["GET", `${coreUrl}/api/v1/items?limit=20`],
      ["GET", `${coreUrl}/api/v1/selected?limit=20`],
      ["GET", `${coreUrl}/api/v1/topics/map`],
      ["GET", `${coreUrl}/api/v1/vendors/map`],
      ["GET", `${coreUrl}/api/v1/stats`],
    ]);
    responses.forEach((response, index) => {
      coreLatency.add(response.timings.duration);
      verify(response, `core-${index}`);
    });
  });

  group("web SSR and proxy reads", () => {
    const paths = ["/", "/items", "/topics", "/reports", "/ask"];
    const path = paths[__ITER % paths.length];
    const response = http.get(`${baseUrl}${path}`);
    webLatency.add(response.timings.duration);
    verify(response, `web-${path}`);
  });

  group("python RAG read-only control path", () => {
    const response = http.get(`${aiUrl}/rag/stats?days=30`);
    aiControlLatency.add(response.timings.duration);
    verify(response, "ai-rag-stats");
  });

  sleep(0.2);
}
