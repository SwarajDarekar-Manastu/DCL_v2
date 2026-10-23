<script lang="ts">
	// Settings › Sources (file 08 §3.2): roots with sign-in status, sync state and counts; the device-code sign-in
	// shown to the operator; "process everything" with its preview first.
	import {
		ApiError,
		listRoots,
		previewSettings,
		processEverything,
		signInState,
		startSignIn,
		type ConfigImpact,
		type RootStatus,
		type SignInState
	} from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';
	import { ago, SIGN_IN_POLL_MS, signInActive } from './sources';

	let roots = $state<RootStatus[] | null>(null);
	let error = $state('');
	let signIn = $state<SignInState | null>(null);
	let everything = $state<ConfigImpact[] | null>(null);
	let notice = $state('');
	let busy = $state(false);
	let reload = $state(0);

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));
	const int = (n: number) => n.toLocaleString('en-US');

	$effect(() => {
		void reload;
		listRoots()
			.then((r) => (roots = r))
			.catch((e) => (error = describe(e)));
		signInState()
			.then((s) => (signIn = s))
			.catch(() => {});
	});

	$effect(() => {
		if (!signInActive(signIn)) return;
		const timer = setTimeout(async () => {
			try {
				signIn = await signInState();
				if (signIn.state === 'signed_in') reload += 1;
			} catch (e) {
				error = describe(e);
			}
		}, SIGN_IN_POLL_MS);
		return () => clearTimeout(timer);
	});

	async function act(run: () => Promise<void>) {
		busy = true;
		error = '';
		notice = '';
		try {
			await run();
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	const beginSignIn = () => act(async () => void (signIn = await startSignIn()));
	const previewEverything = () =>
		act(async () => void (everything = (await previewSettings({ changes: [{ key: 'processing.scope', value: [] }] })).impacts));
	const confirmEverything = () =>
		act(async () => {
			const result = await processEverything();
			everything = null;
			notice = `processing.scope cleared (now version ${result.applied[0]?.version ?? '?'}): every landed file in a downloaded root will be processed.${result.dispatch_started ? ' Dispatch started.' : ''}`;
			reload += 1;
		});
</script>

<div class="grid gap-5">
	{#if error}<Notice tone="error">{error}</Notice>{/if}
	{#if notice}<Notice tone="success">{notice}</Notice>{/if}

	<section aria-label="Roots" class="grid gap-2">
		<h3 class="eyebrow m-0">Roots</h3>
		{#if roots}
			<div class="table-scroll">
				<table class="data-table" aria-label="Roots">
					<thead>
						<tr>
							<th>Root</th><th>Sign-in</th><th>Kept current by</th><th>Last full crawl</th><th>Last delta</th><th class="num">Items</th><th class="num">Landed</th><th class="num">Held by scope</th><th class="num">Pending</th><th class="num">Failed</th><th class="num">Waiting dispatch</th>
						</tr>
					</thead>
					<tbody>
						{#each roots as r (r.root_name)}
							<tr>
								<td class="font-medium">{r.root_name}{#if r.crawl_in_progress}<span class="text-info text-xs">{' · crawling'}</span>{/if}{#if !r.cloud_allowed}<span class="text-muted-foreground text-xs">{' · local only'}</span>{/if}</td>
								<td class={r.auth_status === 'OK' ? '' : 'text-hard font-medium'}>{r.auth_status === 'REAUTH_REQUIRED' ? 'sign-in needed' : r.auth_status}</td>
								<td>{r.kept_current_by}{#if r.subscription_expires_at}<span class="text-muted-foreground text-xs">{` · expires ${r.subscription_expires_at.slice(0, 16).replace('T', ' ')}`}</span>{/if}</td>
								<td class="num" title={r.last_full_crawl_at ?? ''}>{ago(r.last_full_crawl_at)}</td>
								<td class="num" title={r.last_delta_at ?? ''}>{ago(r.last_delta_at)}</td>
								<td class="num font-mono">{int(r.counts.items)}</td>
								<td class="num font-mono">{int(r.counts.landed)}</td>
								<td class="num font-mono">{int(r.counts.held_by_scope)}</td>
								<td class="num font-mono">{int(r.counts.pending_download)}</td>
								<td class="num font-mono {r.counts.download_failed ? 'text-hard' : ''}">{int(r.counts.download_failed)}</td>
								<td class="num font-mono">{int(r.counts.waiting_dispatch)}</td>
							</tr>
							{#if r.recent_errors.length}
								<tr class="hover:bg-transparent">
									<td colspan="11" class="text-xs">
										<details>
											<summary class="text-hard cursor-pointer">{r.recent_errors.length} recent {r.recent_errors.length === 1 ? 'error' : 'errors'}</summary>
											<ul class="m-0 mt-1 list-none p-0">
												{#each r.recent_errors as e, i (i)}<li class="font-mono">{e.path ?? '—'}: {e.error}</li>{/each}
											</ul>
										</details>
									</td>
								</tr>
							{/if}
						{:else}<tr><td colspan="11" class="text-muted-foreground">No roots configured.</td></tr>{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>

	<section aria-label="Microsoft sign-in" class="panel grid gap-2 p-3">
		<h3 class="eyebrow m-0">Microsoft sign-in (delegated, device code)</h3>
		{#if signIn?.state === 'pending' && signIn.user_code}
			<p class="m-0">
				Open <a href={signIn.verification_uri} target="_blank" rel="noopener">{signIn.verification_uri}</a> and enter the code
			</p>
			<p class="m-0 font-mono text-2xl font-semibold tracking-widest" aria-label="Sign-in code">{signIn.user_code}</p>
			{#if signIn.expires_at}<p class="text-muted-foreground m-0 text-xs">The code expires at {signIn.expires_at.slice(11, 16)} UTC. This page updates by itself.</p>{/if}
		{:else if signIn?.state === 'starting'}
			<p class="text-muted-foreground m-0">Asking Microsoft for a code…</p>
		{:else if signIn?.state === 'signed_in'}
			<Notice tone="success">Signed in. Sync uses the new sign-in from now on.</Notice>
		{:else if signIn?.state === 'failed'}
			<Notice tone="error">Sign-in failed{signIn.detail ? `: ${signIn.detail}` : ''}.</Notice>
		{/if}
		{#if !signInActive(signIn)}
			<div><Button size="sm" variant="outline" disabled={busy} onclick={beginSignIn}>Start device-code sign-in</Button></div>
		{/if}
	</section>

	<section aria-label="Process everything" class="panel grid gap-2 p-3">
		<h3 class="eyebrow m-0">Process everything</h3>
		<p class="text-muted-foreground m-0 text-sm">Clears the processing allowlist, so every landed file is processed. Preview first: it shows how many files that is and what it costs.</p>
		{#if everything}
			<ul class="m-0 grid list-none gap-1 p-0 text-sm" aria-label="Process everything impact">
				{#each everything as impact (impact.key)}
					<li>
						{impact.summary}
						{#if impact.estimated_cost_usd !== null}<strong>{` · about $${impact.estimated_cost_usd.toFixed(2)}`}</strong>{/if}
						{#if impact.cost_note}<span class="text-muted-foreground">{` (${impact.cost_note})`}</span>{/if}
					</li>
				{/each}
			</ul>
			<div class="flex gap-2">
				<Button size="sm" disabled={busy} onclick={confirmEverything}>Process everything</Button>
				<Button size="sm" variant="ghost" disabled={busy} onclick={() => (everything = null)}>Cancel</Button>
			</div>
		{:else}
			<div><Button size="sm" variant="outline" disabled={busy} onclick={previewEverything}>Preview</Button></div>
		{/if}
	</section>
</div>
