<script lang="ts">
	import type { RuleDraft, RuleType } from '$lib/api_endpoint';

	interface Props {
		busy: boolean;
		onSubmit: (draft: RuleDraft) => void;
	}

	let { busy, onSubmit }: Props = $props();

	const RULE_TYPES: RuleType[] = ['unit_mapping', 'schema_mapping', 'channel_map', 'supersession', 'ignore_pattern', 'origin_override'];
	let ruleType = $state<RuleType>('unit_mapping');
	let scopeRoot = $state('');
	let scopeFolderId = $state('');
	let scopeGlob = $state('');
	let scopeExtension = $state('');
	let precedence = $state(0);
	let bodyText = $state('{\n  \n}');

	let parsed = $derived.by((): { body: Record<string, unknown> | null; error: string } => {
		try {
			const value = JSON.parse(bodyText);
			if (value === null || typeof value !== 'object' || Array.isArray(value)) return { body: null, error: 'The body must be a JSON object.' };
			return { body: value, error: '' };
		} catch (e) {
			return { body: null, error: `Body is not valid JSON: ${(e as Error).message}` };
		}
	});
	let global = $derived(!scopeRoot && !scopeFolderId && !scopeGlob && !scopeExtension);
	const orNull = (v: string) => (v.trim() ? v.trim() : null);

	function submit(event: SubmitEvent) {
		event.preventDefault();
		if (!parsed.body) return;
		onSubmit({
			rule_type: ruleType,
			scope: {
				scope_root: orNull(scopeRoot),
				scope_folder_id: orNull(scopeFolderId),
				scope_filename_glob: orNull(scopeGlob),
				scope_extension: orNull(scopeExtension)
			},
			body: parsed.body,
			precedence
		});
	}
</script>

<form onsubmit={submit} aria-label="New rule">
	<label
		>Rule type
		<select bind:value={ruleType}>{#each RULE_TYPES as t (t)}<option value={t}>{t}</option>{/each}</select>
	</label>
	<fieldset>
		<legend>Scope (most specific match wins)</legend>
		<label>Root <input bind:value={scopeRoot} placeholder="APU Heater" /></label>
		<label>Folder id <input bind:value={scopeFolderId} placeholder="Graph item id" /></label>
		<label>Filename glob <input bind:value={scopeGlob} placeholder="T*.dat" /></label>
		<label>Extension <input bind:value={scopeExtension} placeholder=".dat" /></label>
	</fieldset>
	{#if global}<p class="warn">No scope: this rule applies everywhere.</p>{/if}
	<label>Precedence <input type="number" bind:value={precedence} /></label>
	<label>Body (JSON; validated by rule type on the server) <textarea rows="8" bind:value={bodyText}></textarea></label>
	{#if parsed.error}<p class="warn">{parsed.error}</p>{/if}
	<button type="submit" disabled={busy || !parsed.body}>Create rule</button>
</form>

<style>
	form,
	fieldset {
		display: grid;
		gap: 0.4rem;
		font-size: 0.82rem;
	}
	fieldset {
		border: 1px solid var(--border);
		border-radius: 0.3rem;
		padding: 0.5rem;
	}
	label {
		display: grid;
		gap: 0.15rem;
	}
	input,
	select,
	textarea {
		font: inherit;
		padding: 0.25rem;
		background: var(--bg);
		color: inherit;
		border: 1px solid var(--border);
		border-radius: 0.25rem;
	}
	textarea {
		font-family: ui-monospace, monospace;
	}
	.warn {
		margin: 0;
		color: var(--warn);
	}
	button {
		justify-self: start;
		font: inherit;
		padding: 0.3rem 0.8rem;
		cursor: pointer;
	}
</style>
