// What saving, previewing and switching off a rule does, per effect (backend/review/rule_answers.py, 2026-10-24):
// a test-data unit rule only proposes; the other kinds act when saved. Words only; no network.

import type { RuleCreated, RulePreview, RuleSimulation, RuleView } from '$lib/api_endpoint';
import type { RuleEffect } from './rules_guide';

const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The notice under the type in the rule form: what saving does for this kind. */
export const EFFECT_NOTICE: Record<RuleEffect, { tone: 'info' | 'warning'; text: string }> = {
	proposes: { tone: 'info', text: 'Saving shows these units on the waiting files as a proposal. A person still applies each one.' },
	decision: { tone: 'info', text: 'A file\'s columns are approved by applying the file, not by a rule.' },
	resolves: { tone: 'warning', text: 'Saving answers the matching open flags the way you would and rebuilds those files.' },
	applies: { tone: 'warning', text: 'The matched documents change at their next rebuild, which saving starts.' }
};

/** A rule that acts when saved: it answers flags or changes documents (the other kinds only propose or record). */
export const isActing = (effect: RuleEffect): boolean => effect === 'resolves' || effect === 'applies';

/** One line for a preview ("N open flags would be answered"). */
export function previewLine(p: RulePreview): string {
	if (p.problem) return `The server will not accept this rule: ${p.problem}`;
	const files = count(p.matched_documents, 'matching file');
	switch (p.effect) {
		case 'resolves':
			return p.resolves_flags
				? `${count(p.resolves_flags, 'open flag')} would be answered, among ${files}.`
				: `No open flag matches now (${files} in scope). A matching flag raised later is answered too.`;
		case 'applies':
			return p.matched_documents ? `${files} would change at the next rebuild, which saving starts.` : 'No file matches yet. Files that match later change when they are built.';
		case 'proposes':
			return p.waiting_documents
				? `${count(p.waiting_documents, 'waiting file')} would show it as a proposal.`
				: 'No file is waiting for it now. Matching files that arrive later show it as a proposal.';
		default:
			return 'Nothing reads this kind; no file would change.';
	}
}

/** The notice after a rule is saved from the Rules page. */
export function savedLine(created: RuleCreated, effect: RuleEffect): string {
	if (effect === 'resolves') {
		const rebuilt = created.rebuilt_doc_ids.length;
		return created.resolved_flags
			? `Rule saved. It answered ${count(created.resolved_flags, 'open flag')}; ${count(rebuilt, 'file')} ${rebuilt === 1 ? 'is' : 'are'} being rebuilt or resumed.`
			: 'Rule saved. No open flag matched yet; a matching flag raised later is answered too.';
	}
	if (effect === 'applies') {
		const rebuilt = created.rebuilt_doc_ids.length;
		return rebuilt
			? `Rule saved. ${count(rebuilt, 'file')} ${rebuilt === 1 ? 'is' : 'are'} being rebuilt to apply it.`
			: 'Rule saved. No file matched yet; files that match later change when they are built.';
	}
	const proposed = created.proposed_files;
	return `Rule saved.${proposed ? ` ${proposed} file${proposed === 1 ? ' now shows' : 's now show'} it as a proposal.` : ''}`;
}

/** The label of the button that switches a saved rule off. */
export const deactivateLabel = (effect: RuleEffect): string => (isActing(effect) ? 'Switch off' : 'Stop proposing');

/** The tooltip of that button. */
export function deactivateTitle(effect: RuleEffect): string {
	if (effect === 'resolves') return 'Switches the rule off. The flags it answered are open again and those files are rebuilt.';
	if (effect === 'applies') return 'Switches the rule off. The files it changed are rebuilt without it.';
	return 'Stops new proposals. Files a person has already approved are never changed.';
}

/** The notice after a rule is switched off. */
export function deactivatedLine(effect: RuleEffect): string {
	if (effect === 'resolves') return 'Rule switched off. The flags it answered are open again and those files are being rebuilt.';
	if (effect === 'applies') return 'Rule switched off. The files it changed are being rebuilt without it.';
	return 'Rule switched off. Approved files are unchanged.';
}

/** The sentence under a saved rule's Simulate button. */
export function simulationLine(sim: RuleSimulation, effect: RuleEffect): string {
	const reach = `Reaches ${count(sim.matched_documents, 'file')}: ${sim.waiting_documents} waiting, ${sim.finished_documents} already processed`;
	return isActing(effect) ? `${reach}.` : `${reach} (a proposal never changes them).`;
}

/** The "Usage" cell of a saved rule: what it has done so far. */
export function usageLine(rule: Pick<RuleView, 'flags_resolved' | 'flags_proposed' | 'flags_decided' | 'files_waiting'>, effect: RuleEffect): string {
	if (effect === 'resolves') return `${count(rule.flags_resolved, 'flag')} answered`;
	if (effect === 'applies') return 'Changes the matching files at their rebuild.';
	return `${rule.flags_proposed} proposed · ${rule.flags_decided} decided · ${count(rule.files_waiting, 'file')} waiting`;
}
