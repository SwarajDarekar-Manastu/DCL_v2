<script lang="ts">
	// One rule offered from a decision just made: prefilled fields, the folder it covers, how many open flags it
	// would answer (POST /review/rules/preview), and the save button (POST /review/rules).
	import { ApiError, createRule, previewRule, type CaseLocation, type RuleCreated, type RulePreview } from '$lib/api_endpoint';
	import CheckIcon from '@lucide/svelte/icons/check';
	import { untrack } from 'svelte';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { previewLine, savedLine } from './rule_effect';
	import { initialValues, offerBody, offerProblem, offerSentence, type RuleOffer } from './rule_from_decision';
	import { caseRuleScope } from './resolution';

	interface Props {
		offer: RuleOffer;
		/** where the decided file lives: the folder the rule is scoped to */
		where: Pick<CaseLocation, 'root_name' | 'folder_id' | 'file_name' | 'extension'>;
		/** called after the rule is saved, so the queue can reload */
		onSaved?: () => void;
	}

	let { offer, where, onSaved }: Props = $props();

	// A card belongs to one offer (keyed by its flag): the fields start from it and the reviewer edits them.
	let values = $state(untrack(() => initialValues(offer)));
	let choice = $state<'folder' | 'folder_pattern'>('folder');
	let pattern = $state('');
	let saved = $state<RuleCreated | null>(null);
	let busy = $state(false);
	let error = $state('');
	let preview = $state<{ signature: string; result: RulePreview | null; error: string } | null>(null);

	let body = $derived(offerBody(offer, values));
	let fieldProblem = $derived(offerProblem(offer, values));
	let scope = $derived.by(() => {
		try {
			return caseRuleScope(choice, where, pattern);
		} catch {
			return null;
		}
	});
	let problem = $derived(fieldProblem ?? (scope ? null : choice === 'folder_pattern' ? 'Type a file name pattern such as T*.dat.' : 'This file has no folder to scope a rule to.'));
	let signature = $derived(JSON.stringify([offer.ruleType, scope, body]));
	let shown = $derived(preview && preview.signature === signature ? preview : null);
	let answers = $derived(shown?.result && !shown.result.problem ? shown.result.resolves_flags : 0);

	// The count follows the fields and the scope, a moment after the last keystroke.
	$effect(() => {
		const asked = signature;
		const current = scope;
		const draft = body;
		if (problem || !current) return;
		const timer = setTimeout(
			() =>
				previewRule({ rule_type: offer.ruleType, scope: current, body: draft })
					.then((result) => (preview = { signature: asked, result, error: '' }))
					.catch((e) => (preview = { signature: asked, result: null, error: e instanceof ApiError ? e.detail : String(e) })),
			300
		);
		return () => clearTimeout(timer);
	});

	async function save() {
		if (problem || !scope) return;
		busy = true;
		error = '';
		try {
			saved = await createRule({ rule_type: offer.ruleType, scope, body, precedence: 0 });
			onSaved?.();
		} catch (e) {
			error = e instanceof ApiError ? e.detail : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<article class="grid gap-3 rounded-md border p-3" aria-label="Rule from the decision about {offer.about}">
	<p class="m-0 text-sm font-medium">
		{offerSentence(offer, values)}
		<code class="text-muted-foreground ml-1 text-xs font-normal">{offer.ruleType}</code>
	</p>
	{#if saved}
		<Notice tone="success">{savedLine(saved, 'resolves')}</Notice>
	{:else}
		{#if offer.ruleType === 'ignore_pattern'}
			<p class="text-muted-foreground m-0 text-xs">The rule answers every matching conflict with "Ignore", also when you accepted this one as it is.</p>
		{/if}
		{#if offer.fields.length}
			<div class="grid gap-3 sm:grid-cols-2">
				{#each offer.fields as f (f.key)}
					<label class="grid gap-1"
						><span class="field-label">{f.label}{f.required ? '' : ' (optional)'}</span>
						<input class="field font-mono" bind:value={values[f.key]} placeholder={f.placeholder} /></label
					>
				{/each}
			</div>
		{/if}
		<fieldset class="m-0 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-0 p-0 text-[13px]">
			<legend class="field-label float-left mr-2">Applies to</legend>
			<label class="flex items-center gap-1.5"><input type="radio" bind:group={choice} value="folder" /> the files in this folder</label>
			<label class="flex items-center gap-1.5"
				><input type="radio" bind:group={choice} value="folder_pattern" /> files in this folder named
				<input class="field h-7 w-28 font-mono" aria-label="File name pattern" bind:value={pattern} placeholder="T*.dat" disabled={choice !== 'folder_pattern'} /></label
			>
		</fieldset>
		{#if problem}
			<p class="text-muted-foreground m-0 text-xs" aria-live="polite">{problem}</p>
		{:else if shown?.error}
			<Notice tone="error">{shown.error}</Notice>
		{:else if shown?.result}
			<Notice tone={shown.result.problem ? 'warning' : 'info'}>{previewLine(shown.result)}</Notice>
		{/if}
		{#if error}<Notice tone="error">{error}</Notice>{/if}
		<Button size="sm" class="justify-self-start" disabled={busy || !!problem || !!shown?.result?.problem} onclick={save}>
			<CheckIcon />{answers ? `Save rule and answer ${answers} open flag${answers === 1 ? '' : 's'}` : 'Save rule'}
		</Button>
	{/if}
</article>
