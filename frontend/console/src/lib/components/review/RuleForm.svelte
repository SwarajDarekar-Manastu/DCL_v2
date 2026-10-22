<script lang="ts">
	import type { RuleDraft, RuleType } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';

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

<form onsubmit={submit} aria-label="New rule" class="grid gap-4">
	<div class="grid grid-cols-[1fr_8rem] gap-3">
		<label class="grid gap-1"
			><span class="field-label">Rule type</span>
			<select class="field font-mono" bind:value={ruleType}>{#each RULE_TYPES as t (t)}<option value={t}>{t}</option>{/each}</select>
		</label>
		<label class="grid gap-1"><span class="field-label">Precedence</span> <input class="field num font-mono" type="number" bind:value={precedence} /></label>
	</div>
	<fieldset class="m-0 grid grid-cols-2 gap-3 rounded-md border p-3">
		<legend class="text-muted-foreground px-1 text-xs font-medium">Scope (most specific match wins)</legend>
		<label class="grid gap-1"><span class="field-label">Root</span> <input class="field" bind:value={scopeRoot} placeholder="APU Heater" /></label>
		<label class="grid gap-1"><span class="field-label">Folder id</span> <input class="field font-mono" bind:value={scopeFolderId} placeholder="Graph item id" /></label>
		<label class="grid gap-1"><span class="field-label">Filename glob</span> <input class="field font-mono" bind:value={scopeGlob} placeholder="T*.dat" /></label>
		<label class="grid gap-1"><span class="field-label">Extension</span> <input class="field font-mono" bind:value={scopeExtension} placeholder=".dat" /></label>
	</fieldset>
	{#if global}<Notice tone="warning">No scope: this rule applies everywhere.</Notice>{/if}
	<label class="grid gap-1"
		><span class="field-label">Body (JSON; validated by rule type on the server)</span>
		<textarea class="field font-mono text-xs" rows="8" spellcheck="false" bind:value={bodyText}></textarea></label
	>
	{#if parsed.error}<Notice tone="warning">{parsed.error}</Notice>{/if}
	<Button type="submit" class="justify-self-start" disabled={busy || !parsed.body}>Create rule</Button>
</form>
