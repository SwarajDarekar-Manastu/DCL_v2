<script lang="ts">
	// "Create a rule" in three steps: which files, what each column is, check and apply.
	// The rule is a channel_proposal: saving it makes the matching halted files show these units, and a person
	// applies each one. Everything it will do is shown before the button (POST /review/rules/preview).
	import {
		ApiError,
		createRule,
		previewRule,
		type FolderChoice,
		type RuleCreated,
		type RulePreview
	} from '$lib/api_endpoint';
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';
	import ArrowRightIcon from '@lucide/svelte/icons/arrow-right';
	import CheckIcon from '@lucide/svelte/icons/check';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import XIcon from '@lucide/svelte/icons/x';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { AMBIENT_OPTIONS, UNIT_GROUPS, type Ambient } from './channel_map';
	import FolderPicker from './FolderPicker.svelte';
	import {
		channelMapBody,
		choiceOf,
		columnsFrom,
		draftFor,
		decided,
		saysText,
		scopeFor,
		slug,
		stepProblem,
		STEPS,
		whereText,
		type Column,
		type Narrowing,
		type Step
	} from './rule_wizard';

	interface Props {
		/** called after a rule is saved, so the list can reload */
		onSaved?: () => void;
	}
	let { onSaved }: Props = $props();

	let step = $state<Step>('files');
	let folder = $state<FolderChoice | null>(null);
	let narrowing = $state<Narrowing>({ glob: '', extension: '' });
	let columns = $state<Column[]>([]);
	let ambient = $state<Ambient>('SEA_LEVEL');
	let match = $state<RulePreview | null>(null);
	let checked = $state<RulePreview | null>(null);
	let saved = $state<RuleCreated | null>(null);
	let busy = $state(false);
	let error = $state('');
	let edited = false;
	let nextKey = 1000;

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));
	let index = $derived(STEPS.findIndex((s) => s.id === step));
	let problem = $derived(stepProblem(step, folder, columns));
	let anyGauge = $derived(columns.some((c) => decided(c) && choiceOf(c)?.gauge_or_abs === 'gauge'));
	let draft = $derived(draftFor(folder, narrowing, columns, ambient));

	// Which files match, as the folder and the filter change; the columns they wait on become the rows of step 2.
	$effect(() => {
		const picked = folder;
		const scope = scopeFor(picked, { ...narrowing });
		if (!picked) {
			match = null;
			return;
		}
		const timer = setTimeout(
			() =>
				previewRule({ rule_type: 'channel_proposal', scope })
					.then((p) => {
						match = p;
						if (!edited) columns = columnsFrom(p.open_channels);
					})
					.catch((e) => (error = describe(e))),
			250
		);
		return () => clearTimeout(timer);
	});

	function pickFolder(next: FolderChoice) {
		folder = next;
		edited = false;
		error = '';
	}

	function addColumn() {
		edited = true;
		columns.push({ key: nextKey++, raw: '', unitId: '', name: '' });
	}

	function removeColumn(key: number) {
		edited = true;
		columns = columns.filter((c) => c.key !== key);
	}

	function typed(column: Column, raw: string) {
		edited = true;
		const follows = column.name === slug(column.raw) || column.name === '';
		column.raw = raw;
		if (follows) column.name = raw.trim() ? slug(raw) : '';
	}

	async function next() {
		if (problem || !folder) return;
		error = '';
		if (step === 'files') {
			step = 'columns';
			return;
		}
		busy = true;
		try {
			checked = await previewRule({ rule_type: 'channel_proposal', scope: scopeFor(folder, narrowing), body: channelMapBody(columns, ambient) });
			step = 'apply';
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	function back() {
		error = '';
		step = step === 'apply' ? 'columns' : 'files';
	}

	async function save() {
		if (!draft) return;
		busy = true;
		error = '';
		try {
			saved = await createRule(draft);
			onSaved?.();
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	function again() {
		saved = null;
		checked = null;
		match = null;
		folder = null;
		columns = [];
		narrowing = { glob: '', extension: '' };
		edited = false;
		step = 'files';
	}

	let proposes = $derived(checked?.waiting_documents ?? 0);
</script>

<section class="panel" aria-labelledby="create-rule-title">
	<div class="panel-header">
		<div class="grid gap-0.5">
			<h2 id="create-rule-title" class="panel-title">Create a rule</h2>
			<p class="text-muted-foreground m-0 text-xs">Say once what a folder's columns probably are. Each waiting file then shows your answer, and a person checks it and applies it, file by file.</p>
		</div>
	</div>

	<div class="panel-body grid gap-5">
		<ol class="m-0 flex list-none flex-wrap gap-2 p-0" aria-label="Steps">
			{#each STEPS as s, i (s.id)}
				<li
					class={['flex items-center gap-2 rounded-md border px-3 py-1.5 text-[13px]', s.id === step ? 'border-foreground bg-muted font-medium' : 'text-muted-foreground']}
					aria-current={s.id === step ? 'step' : undefined}
				>
					<span class={['inline-flex size-5 items-center justify-center rounded-full border text-[11px]', i < index || saved ? 'bg-foreground text-background border-transparent' : '']}>
						{#if i < index || saved}<CheckIcon class="size-3" aria-hidden="true" />{:else}{i + 1}{/if}
					</span>
					<span>{s.title}<span class="text-muted-foreground ml-1.5 hidden font-normal xl:inline">· {s.hint}</span></span>
				</li>
			{/each}
		</ol>

		{#if saved}
			<div class="grid gap-3 rounded-md border p-4" role="status">
				<p class="m-0 flex items-center gap-2 text-base font-medium"><CheckIcon class="text-ok size-4" aria-hidden="true" />Rule saved.</p>
				<p class="m-0 text-sm">
					{#if saved.proposed_files}
						{saved.proposed_files} file{saved.proposed_files === 1 ? ' now shows' : 's now show'} these units as a proposal. Nothing is approved: open each one, check the numbers and press "Apply proposed rule", or skip the file.
					{:else}
						No file was waiting for it. Files that arrive later and match will show these units too, and each still waits for a person.
					{/if}
				</p>
				<div class="flex flex-wrap gap-2">
					<Button size="sm" href={saved.proposed_files ? `/review?proposed_by_rule_id=${saved.rule_id}` : '/review'}>
						{saved.proposed_files ? `Review the ${saved.proposed_files} file${saved.proposed_files === 1 ? '' : 's'}` : 'Open the queue'}
					</Button>
					<Button size="sm" variant="outline" onclick={again}>Create another rule</Button>
				</div>
			</div>
		{:else if step === 'files'}
			<div class="grid gap-4">
				<FolderPicker selected={folder} onPick={pickFolder} />
				<details class="rounded-md border px-3 py-2" open={!!narrowing.glob || !!narrowing.extension}>
					<summary class="cursor-pointer text-[13px] font-medium">Only some of the files in it? (optional)</summary>
					<div class="mt-3 grid gap-3 sm:grid-cols-2">
						<label class="grid gap-1"><span class="field-label">File name pattern</span><input class="field font-mono" placeholder="T*.dat" bind:value={narrowing.glob} /></label>
						<label class="grid gap-1"><span class="field-label">File type</span><input class="field font-mono" placeholder=".dat" bind:value={narrowing.extension} /></label>
					</div>
				</details>
				{#if folder && match}
					<div class="bg-muted/50 grid gap-1.5 rounded-md border px-4 py-3 text-sm" role="status" aria-live="polite">
						{#if match.matched_documents === 0}
							<p class="text-warn m-0 font-medium">No file matches yet. Check the folder or the filter; a rule can still wait for files that arrive later.</p>
						{:else}
							<p class="m-0 font-medium">
								This rule reaches {match.matched_documents} file{match.matched_documents === 1 ? '' : 's'}; {match.waiting_documents} {match.waiting_documents === 1 ? 'is' : 'are'} waiting and would show these units as a proposal.
							</p>
							{#if match.open_channels.length}
								<p class="text-muted-foreground m-0 text-[13px]">They wait on the columns {match.open_channels.map((c) => c.channel).join(', ')}.</p>
							{/if}
							<details>
								<summary class="text-muted-foreground cursor-pointer text-xs">Show {match.sample.length} of them</summary>
								<ul class="m-0 mt-1 grid list-none gap-0.5 p-0 font-mono text-xs">
									{#each match.sample as d (d.doc_id)}<li>{d.path ?? d.title} <span class="text-muted-foreground">{d.status}</span></li>{/each}
								</ul>
							</details>
						{/if}
					</div>
				{/if}
			</div>
		{:else if step === 'columns' && folder}
			<div class="grid gap-4">
				<p class="m-0 text-sm">
					For <strong>{whereText(folder, narrowing)}</strong>: say what each column is. A column you leave out keeps waiting.
				</p>
				<div class="overflow-x-auto rounded-md border">
					<table class="w-full text-sm" aria-label="Columns">
						<thead>
							<tr class="bg-muted/60 text-muted-foreground text-left text-xs">
								<th class="px-2.5 py-1.5 font-medium">Column in the file</th><th class="px-2.5 py-1.5 font-medium">Unit</th><th class="px-2.5 py-1.5 font-medium">Name to use</th><th class="px-2.5 py-1.5"><span class="sr-only">Remove</span></th>
							</tr>
						</thead>
						<tbody>
							{#each columns as column (column.key)}
								<tr class="border-t align-top">
									<td class="px-2.5 py-1.5"><input class="field h-8 w-28 font-mono" aria-label="Column name in the file" value={column.raw} oninput={(e) => typed(column, e.currentTarget.value)} placeholder="y0" /></td>
									<td class="px-2.5 py-1.5">
										<select class="field h-8 w-52" aria-label="Unit of {column.raw || 'the column'}" bind:value={column.unitId} onchange={() => (edited = true)}>
											<option value="">choose a unit…</option>
											{#each UNIT_GROUPS as g (g.quantity)}
												<optgroup label={g.label}>{#each g.choices as c (c.id)}<option value={c.id}>{c.label}</option>{/each}</optgroup>
											{/each}
										</select>
									</td>
									<td class="px-2.5 py-1.5"><input class="field h-8 w-52 font-mono" aria-label="Name to use for {column.raw || 'the column'}" bind:value={column.name} oninput={() => (edited = true)} placeholder="pt_101_chamber_bar_g" /></td>
									<td class="px-2.5 py-1.5"><button type="button" class="text-muted-foreground hover:text-foreground inline-flex size-8 items-center justify-center rounded-md" aria-label="Remove {column.raw || 'this column'}" onclick={() => removeColumn(column.key)}><XIcon class="size-4" aria-hidden="true" /></button></td>
								</tr>
							{:else}
								<tr><td colspan="4" class="text-muted-foreground px-2.5 py-3">No file here waits on a column yet. Add the columns your files will have.</td></tr>
							{/each}
						</tbody>
					</table>
				</div>
				<div class="flex flex-wrap items-center gap-3">
					<Button variant="outline" size="sm" onclick={addColumn}><PlusIcon />Add a column</Button>
					{#if anyGauge}
						<label class="field-label flex items-center gap-2"
							>Gauge readings are relative to
							<select class="field w-56" bind:value={ambient}>{#each AMBIENT_OPTIONS as o (o.value)}<option value={o.value}>{o.label}</option>{/each}</select>
						</label>
					{/if}
				</div>
			</div>
		{:else if step === 'apply' && folder && checked}
			<div class="grid gap-4">
				<div class="grid gap-2 rounded-md border p-4">
					<h3 class="m-0 text-sm font-semibold">The rule</h3>
					<p class="m-0 text-sm"><strong>Where:</strong> {whereText(folder, narrowing)}</p>
					<ul class="m-0 grid list-disc gap-0.5 pl-5 text-sm">
						{#each saysText(columns) as line (line)}<li>{line}</li>{/each}
					</ul>
				</div>
				<div class="bg-muted/50 grid gap-1.5 rounded-md border px-4 py-3 text-sm" role="status" aria-live="polite">
					<h3 class="m-0 text-sm font-semibold">What happens when you save</h3>
					{#if checked.problem}
						<p class="text-hard m-0">The server will not accept this rule: {checked.problem}</p>
					{:else if proposes}
						<p class="m-0">{proposes} waiting file{proposes === 1 ? '' : 's'} will show these units as a proposal. Nothing is approved: someone opens each file, checks the converted numbers and applies it, or skips the file.</p>
					{:else}
						<p class="m-0">No file is waiting for this rule now. Files that arrive later and match will show these units too, and each still waits for a person.</p>
					{/if}
					{#if checked.finished_documents}
						<p class="text-muted-foreground m-0 text-[13px]">{checked.finished_documents} matching file{checked.finished_documents === 1 ? ' is' : 's are'} already processed and will not be changed. To change an approved file, use the Audit page.</p>
					{/if}
					<p class="text-muted-foreground m-0 text-[13px]">A saved rule is never edited. To change it later, save a new one and stop proposing the old one.</p>
				</div>
			</div>
		{/if}

		{#if problem && !saved && step !== 'apply'}<p class="text-muted-foreground m-0 text-xs" aria-live="polite">{problem}</p>{/if}
		{#if error}<Notice tone="error">{error}</Notice>{/if}

		{#if !saved}
			<footer class="flex flex-wrap items-center gap-2 border-t pt-4">
				<Button variant="ghost" size="sm" disabled={step === 'files' || busy} onclick={back}><ArrowLeftIcon />Back</Button>
				{#if step === 'apply'}
					<Button disabled={busy || !draft || !!checked?.problem} onclick={save}>
						<CheckIcon />{proposes ? `Save rule and propose to ${proposes} file${proposes === 1 ? '' : 's'}` : 'Save rule'}
					</Button>
				{:else}
					<Button disabled={busy || !!problem} onclick={next}>Next<ArrowRightIcon /></Button>
				{/if}
			</footer>
		{/if}
	</div>
</section>
