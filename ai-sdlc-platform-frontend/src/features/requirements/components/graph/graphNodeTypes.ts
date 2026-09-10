import { GraphNodeCard } from "./GraphNodeCard";

/**
 * The React Flow node type registry.
 *
 * A plain object, so it lives outside the component's module: a file exporting
 * both cannot hot reload, and the graph canvas is the surface where losing state
 * on every edit is most obvious.
 *
 * React Flow requires this object to be referentially stable across renders,
 * which a module constant guarantees.
 */
export const graphNodeTypes = { design: GraphNodeCard };
