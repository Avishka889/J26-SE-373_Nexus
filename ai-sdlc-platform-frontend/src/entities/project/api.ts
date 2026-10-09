import type { Project, RequirementChatMessage } from "@/types/project";
import { MOCK_PROJECTS, PROJECT_COLORS } from "./fixtures";
import { isLive } from "@/lib/env";
import { http, messageOf } from "@/lib/http";

export interface ProjectsApi {
  list(): Promise<Project[]>;
  get(id: string): Promise<Project | undefined>;
  create(
    name: string,
    description?: string,
    requirementText?: string,
    files?: string[],
  ): Promise<Project>;
  update(id: string, patch: Partial<Project>): Promise<Project | undefined>;
  delete(id: string): Promise<void>;
  appendRequirementChatMessage(
    projectId: string,
    message: Omit<RequirementChatMessage, "id" | "createdAt">,
  ): Promise<Project | undefined>;
}

type Listener = () => void;

/**
 * The one list every component reads, through `useProjectsList`.
 *
 * It is not a fixture store, and treating it as one was a real bug: with projects
 * live the HTTP calls returned server records and nothing wrote them here, so the
 * app went on showing four authored demo projects and a freshly created project
 * was invisible to the route guard, which bounced straight back to the list. The
 * API swapped and nothing read the swap.
 *
 * So both implementations write through. On fixtures it starts seeded; live it
 * starts empty and is filled by the first read.
 */
let projectsDb: Project[] = isLive("projects") ? [] : structuredClone(MOCK_PROJECTS);
const listeners = new Set<Listener>();

/**
 * Where the first read of the list stands.
 *
 * Needed because live starts empty, and "not read yet", "could not be read" and
 * "no such project" have to look different. Without the first, deep linking to a
 * project redirected to the list before the fetch finished. Without the second, a
 * failed read was an empty workspace: "No projects yet" and a button inviting a
 * duplicate, and a deep link that rendered nothing for good.
 */
export interface ProjectsLoad {
  status: "loading" | "loaded" | "failed";
  /** Why the last read failed, as a sentence; null unless it failed. */
  error: string | null;
}

const LOADED: ProjectsLoad = { status: "loaded", error: null };

let load: ProjectsLoad = isLive("projects") ? { status: "loading", error: null } : LOADED;

function emit() {
  listeners.forEach((l) => l());
}

function replaceAll(next: Project[]) {
  projectsDb = next;
  load = LOADED;
  emit();
}

// A new project goes first, as the server lists them, newest first: appended,
// it fell out of Home's three, the sidebar's five and the palette until a reload.
function upsert(project: Project) {
  const at = projectsDb.findIndex((p) => p.id === project.id);
  projectsDb =
    at >= 0
      ? projectsDb.map((existing, index) => (index === at ? project : existing))
      : [project, ...projectsDb];
  emit();
}

export function subscribeProjects(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getProjectsSnapshot(): Project[] {
  return projectsDb;
}

export function projectsAreLoaded(): boolean {
  return load.status === "loaded";
}

export function getProjectsLoad(): ProjectsLoad {
  return load;
}

/**
 * Re-read one project, for a field the server changed without being asked.
 *
 * The naming agent renames a project during its first run, so the sidebar and
 * the header kept showing the truncated requirement text until a full page
 * reload replaced the list. Refreshing one row is cheaper than the whole list
 * and is all that changes.
 */
export async function refreshProject(id: string): Promise<void> {
  if (!isLive("projects")) return;
  const project = await projectsApi.get(id);
  if (project) upsert(project);
}

/**
 * Fill the list from wherever projects come from.
 *
 * Called once at startup, and again by whatever offers a retry. On fixtures it
 * only marks the list read; live it is the fetch that makes a deep link work, and
 * a failure is recorded with its reason before it is thrown. A retry keeps the
 * failure showing until it succeeds, so a panel does not flicker into a loader.
 */
let reading: Promise<void> | null = null;

export async function hydrateProjects(): Promise<void> {
  if (!isLive("projects")) {
    load = LOADED;
    return;
  }
  // One read at a time: sign-in, the guard and a retry can all ask at once,
  // and two overlapping reads are the same read twice.
  reading ??= (async () => {
    try {
      replaceAll(await projectsApi.list());
    } catch (error) {
      // A list that was read stays: the lists read again whenever they open,
      // and a server that blinked must not turn them into an error panel.
      if (load.status !== "loaded") {
        load = { status: "failed", error: messageOf(error, "The project list could not be read.") };
        emit();
      }
      throw error;
    } finally {
      reading = null;
    }
  })();
  return reading;
}

/**
 * Forget every project, at sign-out.
 *
 * The next account to sign in on this tab reads its own list; without this it
 * saw the last one's until the read landed.
 */
export function forgetProjects(): void {
  projectsDb = isLive("projects") ? [] : structuredClone(MOCK_PROJECTS);
  load = isLive("projects") ? { status: "loading", error: null } : LOADED;
  emit();
}

function createFixtureProjectsApi(): ProjectsApi {
  return {
    async list() {
      return structuredClone(projectsDb);
    },
    async get(id) {
      return structuredClone(projectsDb.find((p) => p.id === id));
    },
    async create(name, description = "", requirementText = "", files = []) {
      const id = `proj_${Date.now().toString(36)}`;
      const now = new Date().toISOString();
      const color = PROJECT_COLORS[projectsDb.length % PROJECT_COLORS.length];
      const project: Project = {
        id,
        name: name.trim(),
        description,
        status: "draft",
        createdAt: now,
        updatedAt: now,
        // Text typed into a composer arrives here. It is the start signal for the
        // design run, the same way it is for the orchestrator: there is no
        // separate call that says "now begin".
        requirementText,
        files,
        requirementChat: [],
        reqPhase: "input",
        progress: 0,
        techStack: [],
        color,
      };
      projectsDb = [project, ...projectsDb];
      emit();
      return structuredClone(project);
    },
    async update(id, patch) {
      let updated: Project | undefined;
      projectsDb = projectsDb.map((p) => {
        if (p.id !== id) return p;
        updated = { ...p, ...patch, updatedAt: new Date().toISOString() };
        return updated;
      });
      emit();
      return updated ? structuredClone(updated) : undefined;
    },
    async delete(id) {
      projectsDb = projectsDb.filter((p) => p.id !== id);
      emit();
    },
    async appendRequirementChatMessage(projectId, message) {
      let updated: Project | undefined;
      projectsDb = projectsDb.map((p) => {
        if (p.id !== projectId) return p;
        const entry: RequirementChatMessage = {
          ...message,
          id: `chat_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
          createdAt: new Date().toISOString(),
        };
        const chat = [...(p.requirementChat ?? []), entry];
        const requirementText =
          message.type === "source_requirement" && message.role === "user"
            ? p.requirementText.trim()
              ? `${p.requirementText.trim()}\n\n${message.content}`
              : message.content
            : p.requirementText;
        updated = { ...p, requirementChat: chat, requirementText, updatedAt: entry.createdAt };
        return updated;
      });
      emit();
      return updated ? structuredClone(updated) : undefined;
    },
  };
}

function createHttpProjectsApi(): ProjectsApi {
  // Every method writes what the server said into the shared list before
  // returning it. The server's record is the truth, so there is nothing to
  // reconcile and no refetch to wait for: a create can navigate straight to the
  // project it just made.
  return {
    list: async () => {
      const projects = await http.get<Project[]>("/projects");
      replaceAll(projects);
      return projects;
    },
    get: async (id) => {
      const project = await http.get<Project>(`/projects/${id}`);
      upsert(project);
      return project;
    },
    // One call: the server creates the project and, given requirement text,
    // queues its design run in the same transaction. It was a POST and then a
    // PATCH carrying the text, and a PATCH that failed left a project with no
    // requirements in the list, which a retry then duplicated.
    create: async (name, description = "", requirementText = "", files = []) => {
      const project = await http.post<Project>("/projects", {
        name,
        description,
        requirementText,
        files,
      });
      upsert(project);
      return project;
    },
    update: async (id, patch) => {
      const project = await http.patch<Project>(`/projects/${id}`, patch);
      upsert(project);
      return project;
    },
    delete: async (id) => {
      await http.delete<void>(`/projects/${id}`);
      projectsDb = projectsDb.filter((p) => p.id !== id);
      emit();
    },
    appendRequirementChatMessage: async (projectId, message) => {
      const project = await http.post<Project>(`/projects/${projectId}/requirement-chat`, message);
      upsert(project);
      return project;
    },
  };
}

export const projectsApi: ProjectsApi = isLive("projects")
  ? createHttpProjectsApi()
  : createFixtureProjectsApi();
