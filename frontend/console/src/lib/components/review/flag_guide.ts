import type { FlagView, ResolutionAction } from '$lib/api_endpoint';

/** One flag type, or one reading of CONFLICT (what its evidence says it is). */
export type GuideKey = FlagView['flag_type'] | 'CONFLICT_CHECK' | 'CONFLICT_NOTE';

export interface GuideChoice {
	/** The console option this line names; null when it only explains. Checked against the server's list by a backend test. */
	action: ResolutionAction | null;
	text: string;
}

export interface FlagGuide {
	/** One line: what the system found. */
	what: string;
	/** One line: what the reviewer has to decide. */
	decide: string;
	choices: GuideChoice[];
	/** Shown when the reviewer cannot judge from here. */
	unsure: string;
}

const OPEN_HINT = 'Cannot open the file here? Use "Open in viewer" or "Open in OneDrive" above.';

export const FLAG_GUIDE: Record<GuideKey, FlagGuide> = {
	UNIT_AMBIGUITY: {
		what: 'A column of numbers has no unit, so the system cannot convert or compare it.',
		decide: 'Pick the unit the sensor really records.',
		choices: [
			{ action: 'set_unit', text: 'Set channel unit: choose it in the list (the suggestion is preselected when the file hints at one).' },
			{ action: null, text: 'For pressure, say gauge (relative to air) or absolute.' }
		],
		unsure: `Ask whoever ran the test, or leave open: other columns still work. ${OPEN_HINT}`
	},
	SCHEMA_UNKNOWN: {
		what: 'A table or data block has a layout the system does not recognise.',
		decide: 'Say which column or key means what.',
		choices: [
			{ action: 'map_columns', text: 'Map columns: name what each column holds.' },
			{ action: 'map_json_keys', text: 'Map JSON keys: say which section each key belongs to.' },
			{ action: 'mark_junk', text: 'Junk whole file if nothing in it is useful for search.' }
		],
		unsure: `Leave open: the rest of the file is still searchable. ${OPEN_HINT}`
	},
	LOW_CONFIDENCE_EXTRACTION: {
		what: 'The system is not sure it read a page, image, table or handwritten entry right.',
		decide: 'Compare the reading with the picture.',
		choices: [
			{ action: 'set_value', text: 'Type the value (its label is on the page), or tick illegible.' },
			{ action: 'choose_table', text: 'Choose table version A or B when two readings differ.' },
			{ action: 'ignore', text: 'Keep as read if it is right.' },
			{ action: 'mark_junk', text: 'Junk the page, image or table if it shows nothing useful; only it leaves search.' }
		],
		unsure: 'Leave open: answers will mark this value as uncertain.'
	},
	PARSE_FAILURE: {
		what: 'The file could not be opened or read.',
		decide: 'Decide whether the file is worth fixing.',
		choices: [
			{ action: 'skip', text: 'Skip whole file if it is not needed.' },
			{ action: 'mark_junk', text: 'Junk whole file if it should never be indexed.' }
		],
		unsure: `Uploading a readable copy is not possible from the console yet; ask the team. ${OPEN_HINT}`
	},
	UNSUPPORTED_FORMAT: {
		what: 'The system has no reader for this kind of file yet.',
		decide: 'Decide whether it matters.',
		choices: [
			{ action: 'watch', text: 'Notify when an adapter exists, if you want it indexed later.' },
			{ action: 'skip', text: 'Skip whole file if it does not matter.' },
			{ action: 'mark_junk', text: 'Junk whole file if it never will.' }
		],
		unsure: 'Leave open: nothing else is blocked.'
	},
	CONFLICT: {
		what: 'Two sources state different values for the same thing, such as two plan numbers.',
		decide: 'Say which one is right.',
		choices: [
			{ action: 'choose_source', text: 'Pick the authoritative source: A or B.' },
			{ action: 'mark_superseded', text: 'Mark a document superseded when one is just the older version.' },
			{ action: 'accept_both', text: 'Accept both if both are valid.' },
			{ action: 'ignore', text: 'Ignore if it does not matter.' }
		],
		unsure: `Leave open: both stay searchable and answers will show the disagreement. ${OPEN_HINT}`
	},
	CONFLICT_CHECK: {
		what: 'A check on this file failed: what was found lies outside what the system expects (a limit or a rule).',
		decide: 'Decide whether the file is still usable as it is.',
		choices: [
			{ action: 'accept_both', text: 'Accept as it is if the finding is real or harmless.' },
			{ action: 'ignore', text: 'Ignore if the check does not apply to this file.' }
		],
		unsure: `Leave open: the file stays searchable. ${OPEN_HINT}`
	},
	CONFLICT_NOTE: {
		what: 'The system noted something to confirm about this file, for example two test plans named in its folder path, or LaTeX files grouped without a main file. The note above says which.',
		decide: 'Check that the note is right for this file.',
		choices: [
			{ action: 'accept_both', text: 'Accept as it is if the note is right.' },
			{ action: 'ignore', text: 'Ignore if it does not matter.' }
		],
		unsure: 'Leave open: the file is indexed either way and nothing is blocked.'
	},
	SENSITIVE_CONTENT: {
		what: 'The file seems to contain a password, key or personal data.',
		decide: 'Decide whether it may be indexed.',
		choices: [
			{ action: 'approve_internal', text: 'Approve for internal indexing if it is safe (admin only).' },
			{ action: 'exclude', text: 'Exclude permanently if it must never be searchable.' }
		],
		unsure: 'Leave open: the file stays out of search until you decide.'
	},
	HELD_LARGE_FILE: {
		what: 'A very large file was not downloaded automatically.',
		decide: 'Decide whether to fetch it.',
		choices: [
			{ action: 'approve_download', text: 'Approve download to fetch and index it.' },
			{ action: 'skip', text: 'Skip whole file to leave it out.' }
		],
		unsure: 'Leave open: nothing else is blocked.'
	},
	CLOUD_RESTRICTED: {
		what: 'The file may not be sent to the cloud model for reading.',
		decide: 'Usually nothing: it is read with local tools only.',
		choices: [{ action: 'ignore', text: 'Ignore to close the flag once you have seen it.' }],
		unsure: 'Leave open: the file is read only with local tools.'
	}
};

/** Which guide fits a flag: a CONFLICT is read by what its evidence says it is. */
export function guideKeyFor(flag: Pick<FlagView, 'flag_type' | 'evidence'>): GuideKey {
	if (flag.flag_type !== 'CONFLICT') return flag.flag_type;
	const relation = flag.evidence?.kind === 'conflict' ? flag.evidence.relation : 'sources_disagree';
	return relation === 'check_failed' ? 'CONFLICT_CHECK' : relation === 'note' ? 'CONFLICT_NOTE' : 'CONFLICT';
}

export function guideFor(key: GuideKey): FlagGuide {
	return FLAG_GUIDE[key];
}

export const guideWords = (guide: FlagGuide): number =>
	[guide.what, guide.decide, ...guide.choices.map((c) => c.text), guide.unsure].join(' ').split(/\s+/).length;
