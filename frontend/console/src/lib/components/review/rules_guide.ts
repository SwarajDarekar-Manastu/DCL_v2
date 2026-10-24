import type { RuleType } from '$lib/api_endpoint';
import auditEdit from '$asset/rules-guide/10-audit-edit.png';
import caseProposal from '$asset/rules-guide/9-case-proposal.png';
import preview from '$asset/rules-guide/3-preview.png';
import queue from '$asset/rules-guide/1-queue.png';
import rulesPage from '$asset/rules-guide/5-rules-page.png';
import scope from '$asset/rules-guide/4-scope.png';
import wizardApply from '$asset/rules-guide/8-wizard-apply.png';
import wizardColumns from '$asset/rules-guide/7-wizard-columns.png';
import wizardFiles from '$asset/rules-guide/6-wizard-files.png';

export const GUIDE_TITLE = 'How rules work';
export const GUIDE_INTRO = 'A rule gives an answer once. Test-data units are proposed for a person to apply; every other kind acts when you save it.';

export interface GuideImage {
	src: string;
	alt: string;
	caption: string;
}

export interface GuideStep {
	id: string;
	title: string;
	summary: string;
	points: string[];
	/** What the reader ends up with after this step. */
	get: string;
	images: GuideImage[];
}

export const GUIDE_STEPS: GuideStep[] = [
	{
		id: 'idea',
		title: 'A rule is a proposal you make once',
		summary:
			'Many halted files ask the same question: same rig, same columns, no unit. A rule says what that folder\'s columns probably are. Every waiting file in the folder shows your answer, and so does every matching file that arrives later.',
		points: [
			'A unit rule never approves a file. A person opens each file, checks the numbers, and applies the proposal or skips the file.',
			'The queue shows how many files wait in a folder ("unblocks 12"). That is how many one rule can fill in.',
			'A test-data unit is only proposed; a person still applies it. The other kinds of rule act when saved: see "Other kinds of rules" at the end.'
		],
		get: 'You answer once. Every matching file starts with your answer filled in.',
		images: [{ src: queue, alt: 'The review queue, each case with the number of files it unblocks', caption: 'The queue, biggest first. Each case says how many files it unblocks.' }]
	},
	{
		id: 'folder',
		title: '1 · Choose the files',
		summary: 'On this page, "Create a rule" starts with a search for the folder. Type part of its name, or pick one from the list.',
		points: [
			'With nothing typed, the list shows the folders that hold files waiting for a decision, most first. "12 waiting" means 12 halted files.',
			'The rule covers the folder and the folders inside it. Narrow it with a file name pattern such as T*.dat if only some files should follow it.',
			'The box under the list says how many files match and which columns they are waiting on, before you go any further.'
		],
		get: 'You see exactly which files the rule would reach.',
		images: [{ src: wizardFiles, alt: 'Create a rule, step 1: a folder is chosen and the match box counts the files', caption: 'Step 1. The folder list, and the count of files that match and wait.' }]
	},
	{
		id: 'columns',
		title: '2 · Say what each column is',
		summary: 'One row per column the files wait on, already filled in from the files themselves. Choose the unit of each.',
		points: [
			'"Name to use" is what the rest of the system calls the column. It starts as the column name; give it a meaningful one if you know it.',
			'For gauge pressure, say what it is relative to (sea-level air by default).',
			'A column you leave out gets no proposal. Use "Add a column" for one the list did not find.'
		],
		get: 'Every column you set is proposed for all matching files.',
		images: [{ src: wizardColumns, alt: 'Create a rule, step 2: a row per column with a unit and a name', caption: 'Step 2. Units are chosen per column; the ambient reference appears for gauge units.' }]
	},
	{
		id: 'save',
		title: '3 · Check it, then save',
		summary: 'The last step spells the rule out in words and says what saving will do. Nothing has changed until you press the button.',
		points: [
			'"What happens when you save" counts the waiting files that will show your units. The button repeats the number: "Save rule and propose to 12 files".',
			'Files that were already processed are listed but not changed.',
			'If the server will not accept the rule, the reason is shown here and Save stays off.'
		],
		get: 'The files show your units. None is approved.',
		images: [{ src: wizardApply, alt: 'Create a rule, step 3: the rule in words and what saving will do', caption: 'Step 3. The rule in words, its effect, and the button that saves it.' }]
	},
	{
		id: 'apply',
		title: 'Then a person applies it, file by file',
		summary: 'After saving, "Review the 12 files" opens the queue filtered to the files the rule reached. Open one: a blue box says a rule proposes its units and the converted numbers are already shown.',
		points: [
			'If the numbers look right, press "Apply proposed rule". The file is approved in your name and carries on.',
			'If a number looks wrong, the box says so. Change the unit and use "Apply all and resume", or press "Skip file".',
			'The same happens to a matching file that arrives later: it halts and waits with your units filled in.'
		],
		get: 'Every file is decided by a person, in seconds when the proposal is right.',
		images: [{ src: caseProposal, alt: 'A halted file with the blue box: a rule proposes the units, Apply proposed rule', caption: 'A file with a proposal: check the converted numbers, then apply or skip.' }]
	},
	{
		id: 'after',
		title: 'Saved rules, "Stop proposing" and "Switch off"',
		summary: 'The rule appears under "Saved rules" with how many files it reached and what happened to them.',
		points: [
			'"12 proposed · 3 decided · 9 waiting" tells you how far it has got.',
			'Simulate on a saved rule shows how many files it reaches now. Nothing changes.',
			'"Stop proposing" switches a unit proposal off for new proposals. It never touches a file a person has already approved.',
			'"Switch off" on a rule that acts opens the flags it answered again and rebuilds those files.',
			'A rule is never edited. To change one, save a new one and stop the old one.',
			'Export YAML saves the active rules, so a rebuilt system starts with the team\'s knowledge.'
		],
		get: 'A clear record of what was proposed, who proposed it and what became of it.',
		images: [{ src: rulesPage, alt: 'The Rules page: Create a rule, then Saved rules', caption: 'The Rules page: create at the top, the list of saved rules below.' }]
	},
	{
		id: 'audit',
		title: 'Fixing a decision later: the Audit page',
		summary: 'Each file\'s approved units live in the Audit tab, not here. Find the file, open its decisions and change them there.',
		points: [
			'"Find a file" on the Audit page searches by name or path. Each file shows who approved each unit, when, and which rule proposed it.',
			'To change a unit, press Edit, choose the new unit, and write why. The file is rebuilt with the new unit.',
			'Any other kind of decision can be reopened from the same page, so the file is decided again.',
			'Every edit records your sign-in and your reason.'
		],
		get: 'A decision can always be corrected, and the log says who did it and why.',
		images: [{ src: auditEdit, alt: 'The Audit page for one file: decisions, who approved them, and the Edit button', caption: 'A file in the Audit tab: who decided what, and the edit form with a reason.' }]
	},
	{
		id: 'from-case',
		title: 'Or propose while you review a file',
		summary:
			'A halted file in the queue opens as a table of its columns. Pick the units, press "Preview all" to see the converted numbers, and apply. Under the table, "Also propose to" saves the same units as a rule for other files.',
		points: [
			'no other file: only this file is decided.',
			'the other files in this folder: one proposal rule for the folder; each waiting file shows these units.',
			'files in this folder named …: the same, for names that match a pattern.'
		],
		get: 'This file is approved now, and the others have your answer waiting for their check.',
		images: [
			{ src: preview, alt: 'The channel table after Preview all, converted values in the last column', caption: 'After "Preview all" the last column shows each column in the unit you chose. A range that looks absurd means the unit is wrong.' },
			{ src: scope, alt: 'Also propose to: no other file, the other files in this folder, files named', caption: '"Also propose to" under the table, with the number of files the choice reaches.' }
		]
	},
	{
		id: 'from-decision',
		title: 'Make a rule from a decision you just made',
		summary:
			'After you resolve flags in the queue, a box under them offers to save the same answer as a rule for the folder. It is already filled in from what you decided and from the flag.',
		points: [
			'It is offered after: ignoring or accepting a conflict, picking a source, setting the unit of a table or prose number, and mapping the keys of a JSON file.',
			'Edit the fields, choose the whole folder or a file name pattern, and read "N open flags would be answered" before you save.',
			'Saving answers the matching open flags in other files and rebuilds those files. The file you just decided is not touched again.',
			'Test-data units are not offered here. Use "Also propose to" under the table.'
		],
		get: 'The same call is made once for the whole folder, and you see how many flags it reaches first.',
		images: []
	},
	{
		id: 'priority',
		title: 'When two rules match, the closest one wins',
		summary: 'When two rules both match a file, the more specific one is shown. Most specific first:',
		points: [
			'The file\'s own folder, then a farther folder.',
			'A filename pattern, then a file type, then the whole root, then everywhere.',
			'Still tied: your own rules beat learned ones, then the higher precedence number, then the newest.',
			'A rule that does not mention a column does not hide a broader rule that does.'
		],
		get: 'A rule for one folder beats a broad one, so you can make exceptions safely.',
		images: []
	},
	{
		id: 'advanced',
		title: 'Other kinds of rules (advanced)',
		summary: 'At the bottom of this page, "Advanced: write a rule as JSON" saves the other kinds of rule.',
		points: [
			'A unit proposal fills in files for a person to apply. Every other kind acts when you save it: it answers the open flags it matches the way you would, or changes the files it matches, and those files are rebuilt.',
			'These kinds answer flags: ignore_pattern (accept one kind of finding), column_unit (the unit of a table or prose number), source_choice (which side of a disagreement wins), schema_mapping (what columns or JSON keys mean).',
			'These kinds change files: origin_override (internal or external) and supersession (one document replaces another).',
			'A flag a person reopened is never answered by a rule again, and a test-data unit is never answered by a rule: a person approves it.',
			'"Preview" says how many open flags a rule would answer before you save it. "Switch off" opens the flags it answered again and rebuilds those files.',
			'A file\'s approved units are not a rule you write; they are made when a person applies a file.'
		],
		get: 'You know which rules answer for you, which change files, and which only propose.',
		images: []
	}
];

/**
 * proposes: fills in the units of test-data files for a person to approve;
 * decision: a person's approval of one file;
 * resolves: answers the open flags it matches the way a person would, and the files are rebuilt;
 * applies: changes the documents it matches at their rebuild.
 */
export type RuleEffect = 'proposes' | 'decision' | 'resolves' | 'applies';

export interface RuleTypeHelp {
	what: string;
	effect: RuleEffect;
	example: Record<string, unknown>;
}

const CHANNELS_EXAMPLE = {
	channels: { y0: { canonical_name: 'pt_101_chamber_bar_g', physical_quantity: 'pressure', unit: 'bar', gauge_or_abs: 'gauge' } },
	ambient_condition: 'SEA_LEVEL'
};

export const RULE_TYPE_HELP: Record<RuleType, RuleTypeHelp> = {
	channel_proposal: {
		effect: 'proposes',
		what: 'Proposes the name, quantity and unit of each column of a folder\'s test-data files. Each waiting file shows it; a person applies it.',
		example: CHANNELS_EXAMPLE
	},
	unit_mapping: {
		effect: 'proposes',
		what: 'Proposes what unit one column is in. It is saved as a column proposal.',
		example: { channel: 'y0', unit: 'bar', quantity: 'pressure', gauge_or_abs: 'gauge', ambient_condition: 'SEA_LEVEL' }
	},
	channel_map: {
		effect: 'decision',
		what: 'A person\'s approval of one file\'s columns. It is made by applying a file and edited on the Audit page, never written by hand.',
		example: CHANNELS_EXAMPLE
	},
	schema_mapping: {
		effect: 'resolves',
		what: 'Says which section each JSON key belongs to (key_to_section) or what each table column means (columns). Answers the open flags it matches the way you would and rebuilds those files.',
		example: { key_to_section: { summary: 'Summary', results: 'Test results' } }
	},
	supersession: {
		effect: 'applies',
		what: 'Says that the files its scope matches replace one older document (the older one leaves default search). Saving rebuilds those files.',
		example: { superseded_doc_id: '00000000-0000-0000-0000-000000000000', reason: 'Replaced by the newer issue' }
	},
	ignore_pattern: {
		effect: 'resolves',
		what: 'Accepts one kind of finding in its scope: conflicts are ignored, low-confidence readings keep the model\'s answer. Needs a flag_type and a reason; answers the open flags it matches and rebuilds those files.',
		example: { reason: 'Known rig offset, accepted in this folder', flag_type: 'CONFLICT', relation: 'check_failed', subject_contains: 'limit' }
	},
	origin_override: {
		effect: 'applies',
		what: 'Marks the files its scope matches as internal or external, which changes how far they are trusted. They change at their next rebuild, which saving starts.',
		example: { source_origin: 'external_kept', trust_tier: 4 }
	},
	column_unit: {
		effect: 'resolves',
		what: 'Sets the unit of a table or prose number by its column or label name (unit null keeps it as text). Answers the open flags it matches the way you would and rebuilds those files, never for test-data channels.',
		example: { column: 'Pressure*', unit: 'psi' }
	},
	source_choice: {
		effect: 'resolves',
		what: 'Says which side of a two-sided disagreement wins, by its subject and the label of the side to prefer (such as folder or content). Answers the open flags it matches the way you would and rebuilds those files.',
		example: { subject: 'test_plan_id', prefer: 'content' }
	}
};

export const exampleBody = (type: RuleType): string => JSON.stringify(RULE_TYPE_HELP[type].example, null, 2);
