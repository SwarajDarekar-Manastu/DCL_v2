<script lang="ts">
	import type { RuleDraft, RuleType } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { exampleBody, RULE_TYPE_HELP } from './rules_guide';

	interface Props {
		busy: boolean;
		onSubmit: (draft: RuleDraft) => void;
	}

	let { busy, onSubmit }: Props = $props();

	// A file's approval (channel_map) is made by applying a file, never by a rule: it is not offered here.
	const RULE_TYPES: RuleType[] = ['channel_proposal', 'schema_mapping', 'supersession', 'ignore_pattern', 'origin_override'];
	let ruleType = $state<RuleType>('channel_proposal');
	let scopeRoot = $state('');
	let scopeFolderId = $state('');
	let scopeGlob = $state('');
	let scopeExtension = $state('');
	let precedence = $state(0);
	let bodyText = $state(exampleBody('channel_proposal'));
	let lastExample = exampleBody('channel_proposal');

	function changeType() {
		// An example the reviewer has not touched follows the type; their own text is kept.
		if (bodyText === lastExample) bodyText = lastExample = exampleBody(ruleType);
		else lastExample = exampleBody(ruleType);
	}

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

<form onsubmit={submit} aria-label="New rule" class="grid gap-4">
	<div class="grid grid-cols-[1fr_8rem] gap-3">
		<label class="grid gap-1"
			><span class="field-label">Rule type</span>
			<select class="field font-mono" bind:value={ruleType} onchange={changeType}>{#each RULE_TYPES as t (t)}<option value={t}>{t}</option>{/each}</select>
		</label>
		<label class="grid gap-1"><span class="field-label">Precedence</span> <input class="field num font-mono" type="number" bind:value={precedence} /></label>
	</div>
	<p class="text-muted-foreground m-0 -mt-2 text-xs">{RULE_TYPE_HELP[ruleType].what}</p>
	{#if RULE_TYPE_HELP[ruleType].effect === 'stored'}
		<Notice tone="warning">Nothing in the pipeline reads this kind of rule yet. It is saved and listed, and no file changes.</Notice>
	{/if}
	<fieldset class="m-0 grid grid-cols-2 gap-3 rounded-md border p-3">
		<legend class="text-muted-foreground px-1 text-xs font-medium">Scope (most specific match wins)</legend>
		<label class="grid gap-1"><span class="field-label">Root</span> <input class="field" bind:value={scopeRoot} placeholder="APU Heater" /></label>
		<label class="grid gap-1"><span class="field-label">Folder id</span> <input class="field font-mono" bind:value={scopeFolderId} placeholder="Graph item id" /></label>
		<label class="grid gap-1"><span class="field-label">Filename glob</span> <input class="field font-mono" bind:value={scopeGlob} placeholder="T*.dat" /></label>
		<label class="grid gap-1"><span class="field-label">Extension</span> <input class="field font-mono" bind:value={scopeExtension} placeholder=".dat" /></label>
	</fieldset>
	{#if global}<Notice tone="warning">No scope: this rule applies everywhere.</Notice>{/if}
	<label class="grid gap-1"
		><span class="field-label">Body (JSON, an example for the type; the server checks it)</span>
		<textarea class="field font-mono text-xs" rows="8" spellcheck="false" bind:value={bodyText}></textarea></label
	>
	{#if parsed.error}<Notice tone="warning">{parsed.error}</Notice>{/if}
	<Button type="submit" class="justify-self-start" disabled={busy || !parsed.body}>Save rule</Button>
</form>
