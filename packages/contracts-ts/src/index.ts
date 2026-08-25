/**
 * Generated from contracts/*.schema.json. Do not edit by hand.
 *
 * Regenerate with: npm run gen:contracts
 * The schemas themselves are generated from the Pydantic models in
 * packages/contracts-py, which are the single author of every artefact shape.
 */

export type { ApiContractArtefact, ArmComparison, ContractConflict, ArmCounts, ApiContract, ApiEndpoint, EndpointSchema, SchemaField, EndpointTraces, EntityModel } from "./api-contract";
export type { ArchitectureGraph, GraphEdge, GraphNode, EntityAttribute, Position, ValidationFinding } from "./architecture-graph";
export type { ArchitectureRecommendation, TopologyCandidate, ArchitectureStyleNote } from "./architecture-recommendation";
export type { ChangelogReport, ChangelogAnalysis, ChangelogClaim, ModelCall, ModelCallSettings, RefusedClaim, SignalVote } from "./changelog-report";
export type { CodeRepository, BuildReport, ManifestRow, RepositoryPointer } from "./code-repository";
export type { CodeSnapshot, ContractDiff, EndpointChange, NextSprint, NextSprintStory, Stages, CodeStageState, CodeThreadMessage } from "./code-snapshot";
export type { ContractAgreement, AgreementCounts, AgreementFinding, CodeLocation } from "./contract-agreement";
export type { DependencyUpdates, BaselinePin, RegistryQuery, RejectedUpdate, DependencyUpdate, ReleaseNoteRef, TransitiveShift } from "./dependency-updates";
export type { DeployPlan, EnvironmentProtection, RollbackPolicy, DeployStep, DeployTarget, WiringRule } from "./deploy-plan";
export type { DeploySnapshot, Blocker, CloudResources, AtlasDatabase, RenderService, VercelProject, UpdateDecisionView, DeploymentView, DeploymentStepView, FeedbackDecisionView, Strategy1, Bylevel, DeployStageState, DeployThreadMessage } from "./deploy-snapshot";
export type { DesignSnapshot, ConsistencyFinding, GateState, GateDecision, RunStatus, StageState, StageModelUse, DesignThreadMessage, AskedQuestion } from "./design-snapshot";
export type { FeedbackReport, FeedbackItem } from "./feedback";
export type { HealReport, HealAttempt, GuardCheck, DiffSpan, ClassificationEvidence } from "./heal-report";
export type { ImpactReport, AffectedComponent, ComponentLink, AffectedFile, ChangedSymbol, ExtractionRecord, UpdateImpact, UsageReference, RefusedReference, UnmappedFile } from "./impact-report";
export type { MonitoringReport, DeploymentEvent, ProbeSummary, StateInterval, HealthThresholds } from "./monitoring-report";
export type { PipelineConfig, PipelineFile, FileValidation, StackSupport, ArchitecturalLayout } from "./pipeline-config";
export type { ReleaseCandidate, ExcludedUpdate, SmokeCheck, BuildStepReport } from "./release-candidate";
export type { RemediationProposals, RemediationProposal, PatchHunk, Reverification, VerificationSnapshot, RiskAssessment } from "./remediation-proposal";
export type { RequirementsArtefact, Assumption, ClarifyingQuestion, ParsedRequirement } from "./requirements";
export type { RiskReport, UpdateAssessment, Arbitration, EvidenceRef, Latency, Strategy, RuleSet } from "./risk-report";
export type { RollbackPlan, VerificationCheck, VerifiedRelease, RestoreStep, UpdateRollback } from "./rollback-plan";
export type { SettingsState, AiSettings, PhaseThinking, DatabaseSettings, GitSettings, ProfileSettings, RenderSettings, VercelSettings } from "./settings";
export type { SprintPlan, UserStory, AcceptanceCriterion, VelocityAssumption } from "./sprint-plan";
export type { SprintScope, ScopeStory, ScopeStoryTraces } from "./sprint-scope";
export type { TechStackArtefact, StackCandidate, StackLayer, ScorePart, CountedFact } from "./tech-stack";
export type { TestReport, CoverageEntry, MutationResult, QualityFinding, ToolStep, TestSuite, TestCase, TestTrace } from "./test-report";
export type { TestSnapshot, TestAuditEntry, HealDecision, TestStageState, TestThreadMessage } from "./test-snapshot";
export type { UmlArtefact, UmlDiagram, UseCase, SequenceStep } from "./uml-diagrams";
export type { ValidationReport, DetectorRun, SecurityFinding, EvidenceSpan, CvssFactors, RefusedFinding, TestSummary } from "./validation-report";
export type { WireframesArtefact, WireframeCoverageRow, WireframeFlow, FlowScreen, ScreenBlock, FlowLink } from "./wireframes";
