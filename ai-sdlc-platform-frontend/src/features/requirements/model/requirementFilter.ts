import type { ParsedRequirement, RequirementPriority, RequirementType } from "../api/types";

/**
 * Filtering the requirements list, as data rather than as component state.
 *
 * Kept here so the rules can be tested without rendering anything, and so the
 * count line and the list can never disagree: both read the same result.
 *
 * Filters are additive. Choosing "quality" and "must" means quality requirements
 * that are also must, not the union, because the union of two narrowing choices
 * is a wider list than either, which is not what anyone means by filtering.
 */
export interface RequirementFilter {
  types: RequirementType[];
  priorities: RequirementPriority[];
  /** Low confidence, or corrected by a human. The rows worth a second look. */
  needsAttention: boolean;
  search: string;
}

export const EMPTY_FILTER: RequirementFilter = {
  types: [],
  priorities: [],
  needsAttention: false,
  search: "",
};

export function isFilterActive(filter: RequirementFilter): boolean {
  return (
    filter.types.length > 0 ||
    filter.priorities.length > 0 ||
    filter.needsAttention ||
    filter.search.trim() !== ""
  );
}

/** The analysis decides what needs attention; the client never picks a threshold. */
export function needsAttention(requirement: ParsedRequirement): boolean {
  return requirement.lowConfidence || requirement.adjusted;
}

export function applyRequirementFilter(
  requirements: ParsedRequirement[],
  filter: RequirementFilter,
): ParsedRequirement[] {
  const query = filter.search.trim().toLowerCase();

  return requirements.filter((requirement) => {
    if (filter.types.length > 0 && !filter.types.includes(requirement.type)) return false;
    if (filter.priorities.length > 0 && !filter.priorities.includes(requirement.priority)) {
      return false;
    }
    if (filter.needsAttention && !needsAttention(requirement)) return false;
    if (query) {
      // The id and the source quote are searched too: a reader looking for
      // "R-7" or for a phrase they wrote means both.
      const haystack = [
        requirement.id,
        requirement.text,
        requirement.sourceQuote ?? "",
        requirement.qualityAttribute ?? "",
      ]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

/** Toggle one value in a filter list, which is how every chip behaves. */
export function toggleIn<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}
