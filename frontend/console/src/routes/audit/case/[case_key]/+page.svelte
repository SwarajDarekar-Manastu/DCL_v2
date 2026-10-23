<script lang="ts">
	// One file in the Audit tab: what was decided on it, by whom and when, with the means to correct it
	// (DECISIONS 2026-10-24). Unit decisions are edited in place; every other decision can be reopened.
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, getCase, listAudit, type AuditItem, type CaseDetail } from '$lib/api_endpoint';
	import { session } from '$lib/auth/session.svelte';
	import AuditTimeline from '$lib/components/review/AuditTimeline.svelte';
	import DecisionEditor from '$lib/components/review/DecisionEditor.svelte';
	import ReopenButton from '$lib/components/review/ReopenButton.svelte';
	import { auditUrl } from '$lib/components/review/audit';
	import { decisionText, otherDecisions, waitingFlags } from '$lib/components/review/decisions';
	import { caseHref } from '$lib/components/review/format';
	import EmptyState from '$lib/components/shell/EmptyState.svelte';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';
	import { crumb } from '$lib/components/shell/crumb.svelte';
	import { Button } from '$lib/components/ui/button';
	import ArrowLeftIcon from '@lucide/svelte/icons/arrow-left';

	let caseKey = $derived(page.params.case_key ?? '');
	let detail = $state<CaseDetail | null>(null);
	let history = $state<AuditItem[]>([]);
	let error = $state('');
	let reload = $state(0);

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));
	const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '');

	$effect(() => {
		const key = caseKey;
		void reload;
		let cancelled = false;
		getCase(key)
			.then(async (d) => {
				if (cancelled) return;
				detail = d;
				error = '';
				const ids = [key, ...d.flags.map((f) => f.flag_id)];
				const events = await listAudit({ entity_id: ids, limit: 200 });
				if (!cancelled) history = events.items;
			})
			.catch((e) => !cancelled && ((detail = null), (error = describe(e))));
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		crumb.leaf = detail?.summary.title ?? '';
		return () => (crumb.leaf = '');
	});

	let others = $derived(detail ? otherDecisions(detail) : []);
	let waiting = $derived(detail ? waitingFlags(detail) : []);
	const reopened = () => goto(caseHref(caseKey));
</script>

<RoleGate roles={session.user?.roles ?? []} role="reviewer">
	<Page
		title={detail?.summary.title ?? 'File'}
		description={detail?.summary.path ?? 'The decisions made on this file and the means to correct them.'}
	>
		{#snippet actions()}
			<Button variant="outline" size="sm" href="/audit"><ArrowLeftIcon />Audit</Button>
			<Button variant="outline" size="sm" href={caseHref(caseKey)}>Open in review</Button>
			{#if detail?.summary.doc_id}<Button variant="outline" size="sm" href="/docs/{detail.summary.doc_id}/viewer">Open in viewer</Button>{/if}
		{/snippet}

		{#if error}
			<Notice tone="error">{error}</Notice>
		{:else if detail}
			<div class="grid gap-5">
				<p class="text-muted-foreground m-0 text-sm">
					Document {detail.document_status ?? 'unknown'}. Changes here are recorded with your sign-in
					<strong class="text-foreground">{session.user?.email ?? ''}</strong> and the reason you write.
				</p>

				<DecisionEditor {detail} onChanged={() => (reload += 1)} onReopened={reopened} />

				<section class="panel" aria-labelledby="other-title">
					<div class="panel-header"><h2 id="other-title" class="panel-title">Other decisions</h2></div>
					<div class="panel-body">
						{#if others.length === 0}
							<p class="text-muted-foreground m-0 text-sm">No other decision has been made on this file.</p>
						{:else}
							<ul class="m-0 grid list-none gap-3 p-0" aria-label="Other decisions">
								{#each others as flag (flag.flag_id)}
									<li class="grid gap-1 rounded-md border px-3 py-2">
										<div class="flex flex-wrap items-center gap-2">
											<ToneBadge tone="outline">{flag.flag_type}</ToneBadge>
											<strong class="text-[13px] font-medium">{decisionText(flag)}</strong>
											<span class="text-muted-foreground text-xs">by {flag.resolved_by ?? 'unknown'} · {when(flag.resolved_at)}</span>
										</div>
										<div class="text-xs"><ReopenButton {caseKey} flagIds={[flag.flag_id]} label="Reopen to decide again" onDone={reopened} /></div>
									</li>
								{/each}
							</ul>
						{/if}
					</div>
				</section>

				{#if waiting.length}
					<Notice tone="warning">
						{waiting.length} flag{waiting.length === 1 ? ' is' : 's are'} still waiting for a decision on this file.
						<a href={caseHref(caseKey)}>Open it in review</a>.
					</Notice>
				{/if}

				<section class="grid gap-2" aria-labelledby="history-title">
					<h2 id="history-title" class="m-0 text-base font-semibold">History</h2>
					<AuditTimeline items={history} />
					<p class="m-0 text-xs"><a href={auditUrl({ entity_id: [caseKey, ...detail.flags.map((f) => f.flag_id)] })}>Open this history in the full audit log</a></p>
				</section>
			</div>
		{:else}
			<EmptyState title="Loading the file…" description="" />
		{/if}
	</Page>
</RoleGate>
