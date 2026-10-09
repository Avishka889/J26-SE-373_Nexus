export type FileEntry = {
  path: string;
  type: string;
  /** Informational only - no component reads it, so callers may omit it. */
  lines?: number;
  /** Extra uppercase badges on the tree row, e.g. ["healed"]. */
  tags?: string[];
};

export type FileTreeNode = {
  name: string;
  path: string;
  kind: "file" | "folder";
  children?: FileTreeNode[];
  file?: FileEntry;
};

export type BuildFileTreeOptions = {
  /**
   * Fold a folder that holds nothing but one more folder into a single row,
   * the way VS Code does: src/test/java/com/payflow. Roots are never folded,
   * so frontend/ and backend/ stay legible as roots.
   */
  collapseChains?: boolean;
};

function collapse(nodes: FileTreeNode[]): FileTreeNode[] {
  return nodes.map((node) => {
    if (node.kind !== "folder" || !node.children) return node;

    let current = node;
    let name = node.name;
    while (current.children && current.children.length === 1 && current.children[0].kind === "folder") {
      current = current.children[0];
      name = `${name}/${current.name}`;
    }

    return {
      ...current,
      name,
      children: current.children ? collapse(current.children) : undefined,
    };
  });
}

export function buildFileTree(files: FileEntry[], options: BuildFileTreeOptions = {}): FileTreeNode[] {
  const root: FileTreeNode[] = [];

  for (const file of files) {
    const parts = file.path.split("/");
    let current = root;

    parts.forEach((part, index) => {
      const isFile = index === parts.length - 1;
      const path = parts.slice(0, index + 1).join("/");
      let node = current.find((n) => n.name === part);

      if (!node) {
        node = {
          name: part,
          path,
          kind: isFile ? "file" : "folder",
          children: isFile ? undefined : [],
          file: isFile ? file : undefined,
        };
        current.push(node);
      }

      if (!isFile && node.children) {
        current = node.children;
      }
    });
  }

  const sortNodes = (nodes: FileTreeNode[]) => {
    nodes.sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === "folder" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    nodes.forEach((n) => n.children && sortNodes(n.children));
  };

  sortNodes(root);

  if (!options.collapseChains) return root;

  // Keep the top level intact, fold every chain underneath it.
  return root.map((node) =>
    node.kind === "folder" && node.children ? { ...node, children: collapse(node.children) } : node
  );
}

export function breadcrumbParts(path: string) {
  return path.split("/");
}
