<script lang="ts">
	// Local accounts (admin): create, set roles, deactivate or reactivate, reset password. The API keeps at
	// least one active admin and answers 409 otherwise; its message shows here.
	import {
		ApiError,
		createAccount,
		listAccounts,
		updateAccount,
		type LocalAccount,
		type LocalAccountUpdate
	} from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import Notice from '$lib/components/shell/Notice.svelte';

	type Role = LocalAccount['roles'][number];
	const ROLES: Role[] = ['viewer', 'reviewer', 'admin'];
	const MIN_PASSWORD = 12;

	interface Props {
		me: string;
	}

	let { me }: Props = $props();
	let accounts = $state<LocalAccount[]>([]);
	let error = $state('');
	let notice = $state('');
	let busy = $state(false);
	let draft = $state({ email: '', display_name: '', roles: ['viewer'] as Role[], password: '' });
	let resetFor = $state<string | null>(null);
	let resetPassword = $state('');

	const describe = (e: unknown) => (e instanceof ApiError ? e.detail : String(e));
	const when = (at: string | null) => (at ? at.slice(0, 16).replace('T', ' ') : 'never');

	async function load() {
		try {
			accounts = await listAccounts();
			error = '';
		} catch (e) {
			error = describe(e);
		}
	}

	$effect(() => {
		load();
	});

	async function run(action: () => Promise<unknown>, message: string) {
		busy = true;
		error = '';
		notice = '';
		try {
			await action();
			notice = message;
			await load();
		} catch (e) {
			error = describe(e);
		} finally {
			busy = false;
		}
	}

	function toggle(list: Role[], role: Role, on: boolean): Role[] {
		const next = on ? [...new Set([...list, role])] : list.filter((r) => r !== role);
		return ROLES.filter((r) => next.includes(r));
	}

	const patch = (a: LocalAccount, body: LocalAccountUpdate, message: string) => run(() => updateAccount(a.user_id, body), message);

	async function create(event: SubmitEvent) {
		event.preventDefault();
		const email = draft.email.trim().toLowerCase(); // stored lower-case (users.email CHECK)
		await run(() => createAccount({ ...draft, email }), `Account ${email} created.`);
		if (!error) draft = { email: '', display_name: '', roles: ['viewer'], password: '' };
	}

	async function reset(a: LocalAccount, event: SubmitEvent) {
		event.preventDefault();
		await patch(a, { password: resetPassword }, `Password reset for ${a.email}.`);
		if (!error) {
			resetFor = null;
			resetPassword = '';
		}
	}
</script>

<div class="grid gap-4">
	<div>
		<h2 class="m-0 text-base">Users</h2>
		<p class="text-muted-foreground m-0 text-sm">Local Console accounts. Roles take effect on the user's next request.</p>
	</div>
	{#if error}<Notice tone="error">{error}</Notice>{/if}
	{#if notice}<Notice tone="success">{notice}</Notice>{/if}

	<div class="table-scroll">
		<table class="data-table" aria-label="Accounts">
			<thead><tr><th>Email</th><th>Name</th><th>Roles</th><th>Status</th><th>Last sign-in</th><th></th></tr></thead>
			<tbody>
				{#each accounts as a (a.user_id)}
					<tr class:opacity-60={!a.is_active}>
						<td>{a.email}{a.email === me ? ' (you)' : ''}</td>
						<td>{a.display_name}</td>
						<td>
							<fieldset class="m-0 flex gap-2 border-0 p-0" aria-label="Roles of {a.email}">
								{#each ROLES as role (role)}
									<label class="flex items-center gap-1 text-xs"
										><input
											type="checkbox"
											checked={a.roles.includes(role)}
											disabled={busy}
											onchange={(e) => {
												const roles = toggle(a.roles, role, (e.currentTarget as HTMLInputElement).checked);
												if (roles.length) patch(a, { roles }, `Roles of ${a.email} saved.`);
												else (e.currentTarget as HTMLInputElement).checked = true;
											}}
										/>{role}</label
									>
								{/each}
							</fieldset>
						</td>
						<td>{a.is_active ? 'active' : 'deactivated'}</td>
						<td class="num">{when(a.last_login_at)}</td>
						<td class="whitespace-nowrap">
							<Button
								variant="outline"
								size="sm"
								disabled={busy}
								onclick={() => patch(a, { is_active: !a.is_active }, `${a.email} ${a.is_active ? 'deactivated' : 'reactivated'}.`)}
								>{a.is_active ? 'Deactivate' : 'Reactivate'}</Button
							>
							<Button variant="outline" size="sm" disabled={busy} onclick={() => ((resetFor = resetFor === a.user_id ? null : a.user_id), (resetPassword = ''))}
								>Reset password</Button
							>
						</td>
					</tr>
					{#if resetFor === a.user_id}
						<tr>
							<td colspan="6">
								<form class="flex items-end gap-2" aria-label="Reset password of {a.email}" onsubmit={(e) => reset(a, e)}>
									<label class="field-label grid gap-1"
										>New password (at least {MIN_PASSWORD} characters)
										<input class="field text-foreground" type="password" autocomplete="new-password" minlength={MIN_PASSWORD} required bind:value={resetPassword} />
									</label>
									<Button type="submit" size="sm" disabled={busy}>Set password</Button>
								</form>
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>

	<form class="panel grid gap-3 sm:grid-cols-2" aria-label="New account" onsubmit={create}>
		<h3 class="m-0 text-sm sm:col-span-2">New account</h3>
		<label class="field-label grid gap-1"
			>Email <input class="field text-foreground" type="email" autocomplete="off" required bind:value={draft.email} /></label
		>
		<label class="field-label grid gap-1"
			>Name <input class="field text-foreground" required bind:value={draft.display_name} /></label
		>
		<label class="field-label grid gap-1"
			>Initial password (at least {MIN_PASSWORD} characters)
			<input class="field text-foreground" type="password" autocomplete="new-password" minlength={MIN_PASSWORD} required bind:value={draft.password} /></label
		>
		<fieldset class="m-0 flex items-end gap-3 border-0 p-0">
			<legend class="field-label mb-1">Roles</legend>
			{#each ROLES as role (role)}
				<label class="flex items-center gap-1 text-sm"
					><input type="checkbox" checked={draft.roles.includes(role)} onchange={(e) => (draft.roles = toggle(draft.roles, role, (e.currentTarget as HTMLInputElement).checked))} />{role}</label
				>
			{/each}
		</fieldset>
		<div class="sm:col-span-2"><Button type="submit" disabled={busy || draft.roles.length === 0}>Create account</Button></div>
	</form>
</div>
