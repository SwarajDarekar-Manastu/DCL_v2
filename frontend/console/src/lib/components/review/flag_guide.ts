import type { FlagView } from '$lib/api_endpoint';

export interface FlagGuide {
	/** One line: what the system found. */
	what: string;
	/** One line: what the reviewer has to decide. */
	decide: string;
	/** Short plain-language choices. */
	choices: string[];
	/** Shown when the reviewer cannot judge from here. */
	unsure: string;
}

const OPEN_HINT = 'Cannot open the file here? Use "Open in viewer" or "Open in OneDrive" above.';

export const FLAG_GUIDE: Record<FlagView['flag_type'], FlagGuide> = {
	UNIT_AMBIGUITY: {
		what: 'A column of numbers has no unit, so the system cannot convert or compare it.',
		decide: 'Pick the unit the sensor really records.',
		choices: [
			'Choose the unit in the list (the suggestion is preselected when the file hints at one).',
			'For pressure, say gauge (relative to air) or absolute.'
		],
		unsure: `Ask whoever ran the test, or leave open: other columns still work. ${OPEN_HINT}`
	},
	SCHEMA_UNKNOWN: {
		what: 'A table or data block has a layout the system does not recognise.',
		decide: 'Say which column or key means what.',
		choices: ['Map the columns or keys to the names offered.', 'Ignore it if the table is not useful for search.'],
		unsure: `Leave open: the rest of the file is still searchable. ${OPEN_HINT}`
	},
	LOW_CONFIDENCE_EXTRACTION: {
		what: 'The system read text, a table or handwriting but is not sure it read it right.',
		decide: 'Compare the reading with the picture and fix it if it is wrong.',
		choices: ['Keep the reading if it matches.', 'Type the correct value.', 'Upload a cleaner copy of the file.'],
		unsure: 'Leave open: answers will mark this value as uncertain.'
	},
	PARSE_FAILURE: {
		what: 'The file could not be opened or read.',
		decide: 'Decide whether the file is worth fixing.',
		choices: ['Upload a readable copy (for example, remove the password).', 'Skip the file if it is not needed.'],
		unsure: OPEN_HINT
	},
	UNSUPPORTED_FORMAT: {
		what: 'The system has no reader for this kind of file yet.',
		decide: 'Decide whether it matters.',
		choices: ['Ignore it.', 'Leave open and ask the team to add a reader.'],
		unsure: 'Leave open: nothing else is blocked.'
	},
	CONFLICT: {
		what: 'Two sources disagree: two versions of a document, two plan numbers, or a file that no master includes.',
		decide: 'Say which source is right.',
		choices: ['Pick the correct source (Source A or B).', 'Mark the older document superseded.', 'Accept both if both are valid.'],
		unsure: `Leave open: both sources stay searchable and answers will show the disagreement. ${OPEN_HINT}`
	},
	SENSITIVE_CONTENT: {
		what: 'The file seems to contain a password, key or personal data.',
		decide: 'Decide whether it may be indexed.',
		choices: ['Redact the marked text.', 'Approve for internal indexing if it is safe.'],
		unsure: 'Leave open: the file stays out of search until you decide.'
	},
	HELD_LARGE_FILE: {
		what: 'A very large file was not downloaded automatically.',
		decide: 'Decide whether to fetch it.',
		choices: ['Approve the download.', 'Leave it out.'],
		unsure: 'Leave open: nothing else is blocked.'
	},
	CLOUD_RESTRICTED: {
		what: 'The file may not be sent to the cloud model for reading.',
		decide: 'Decide whether cloud reading is allowed.',
		choices: ['Approve cloud processing.', 'Keep it internal only.'],
		unsure: 'Leave open: the file is read only with local tools.'
	}
};

export function guideFor(flagType: FlagView['flag_type']): FlagGuide {
	return FLAG_GUIDE[flagType];
}
