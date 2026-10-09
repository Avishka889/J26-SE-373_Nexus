import type { Project } from "@/types/project";

const daysAgo = (d: number) => new Date(Date.now() - d * 86400000).toISOString();

// Progress is the server's rule applied to each project's phase, which every
// phase's fixture derives from the project's status as waiting on its review:
// that phase reads 80, the ones before it 100, and the whole is their mean.

export const MOCK_PROJECTS: Project[] = [
  {
    id: "p1",
    name: "NexusPay Banking",
    description: "Digital banking with payments, KYC, and fraud detection",
    status: "testing",
    createdAt: daysAgo(18),
    updatedAt: daysAgo(0),
    requirementText:
      "The system shall allow customers to make payments using credit cards and digital wallets. Integrate Stripe and PayPal. KYC verification is required before processing payments above $1000. All transactions must be audited.",
    files: ["NexusPay-SRS-v2.pdf"],
    requirementChat: [],
    reqPhase: "design-review",
    progress: 70,
    phaseProgress: { design: 100, code: 100, testing: 80, deployment: 0 },
    techStack: ["React", "Spring Boot", "PostgreSQL", "Kubernetes"],
    color: "#2563eb",
  },
  {
    id: "p2",
    name: "MediTrack EHR",
    description: "Electronic health records with HL7 integration",
    status: "code",
    createdAt: daysAgo(12),
    updatedAt: daysAgo(1),
    requirementText:
      "Build an EHR system for clinics with patient records, appointments, prescriptions, and HL7 FHIR interoperability. Role-based access for doctors, nurses, and admins.",
    files: ["MediTrack-Requirements.docx"],
    requirementChat: [],
    reqPhase: "design-review",
    progress: 45,
    phaseProgress: { design: 100, code: 80, testing: 0, deployment: 0 },
    techStack: ["Angular", "Node.js", "MongoDB", "Docker"],
    color: "#22c55e",
  },
  {
    id: "p3",
    name: "ShopFlow Commerce",
    description: "Headless commerce platform with microservices",
    status: "design",
    createdAt: daysAgo(8),
    updatedAt: daysAgo(2),
    requirementText:
      "Create a headless e-commerce platform with product catalog, cart, checkout, inventory sync, and order management. Support multi-tenant storefronts.",
    files: [],
    requirementChat: [],
    reqPhase: "design-review",
    progress: 20,
    phaseProgress: { design: 80, code: 0, testing: 0, deployment: 0 },
    // Empty on purpose. The stack is proposed and chosen in Code Generation, and
    // this project has not reached it, so there is nothing to show. The header
    // renders the chips only when a project actually has a recorded stack.
    techStack: [],
    color: "#3b82f6",
  },
  {
    id: "p4",
    name: "NotifyHub",
    description: "Multi-channel notification orchestration service",
    status: "deploy",
    createdAt: daysAgo(25),
    updatedAt: daysAgo(3),
    requirementText:
      "Design a notification service supporting email, SMS, and push. Include templates, delivery tracking, retries, and preference management.",
    files: ["notify-brief.md"],
    requirementChat: [],
    reqPhase: "design-review",
    progress: 95,
    phaseProgress: { design: 100, code: 100, testing: 100, deployment: 80 },
    techStack: ["React", "Node.js", "PostgreSQL"],
    color: "#f97316",
  },
];

export const PROJECT_COLORS = ["#f97316", "#2563eb", "#3b82f6", "#22c55e", "#ec4899", "#06b6d4"];
