from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

import click
from ape.cli import ConnectedProviderCommand
from ape.cli.arguments import existing_alias_argument, non_existing_alias_argument
from ape.cli.options import account_option, ape_cli_context, network_option
from ape.logging import HIDDEN_MESSAGE
from solders.keypair import Keypair

from ape_solana.constants import ECOSYSTEM_NAME, LAMPORTS_PER_SOL, SOLANA_DEFAULT_PATH

if TYPE_CHECKING:
    from ape.api.accounts import AccountAPI


def import_accounts_module():
    return import_module("ape_solana.accounts")


def is_solana_account(account: "AccountAPI") -> bool:
    return isinstance(account, import_accounts_module().SolanaAccount)


def prompt_for_new_passphrase() -> str:
    return click.prompt(
        "Create Passphrase to encrypt account", hide_input=True, confirmation_prompt=True
    )


@click.group(short_help="Solana tools")
def cli():
    """
    Command-line helpers for the Solana ecosystem.
    """


@cli.group(short_help="Manage local Solana accounts")
def accounts():
    """
    Manage Solana keypairs stored in encrypted keyfiles. Load them in scripts or the
    console with ``accounts.load(alias)``.
    """


@accounts.command(name="list", short_help="List Solana accounts")
@ape_cli_context()
def list_accounts(cli_ctx):
    container = cli_ctx.account_manager.containers[ECOSYSTEM_NAME]
    solana_accounts = list(container.accounts)
    if not solana_accounts:
        cli_ctx.logger.warning("No Solana accounts found.")
        return

    plural_suffix = "s" if len(solana_accounts) > 1 else ""
    click.echo(f"Found {len(solana_accounts)} account{plural_suffix}:")
    for account in solana_accounts:
        click.echo(f"  {account.address} (alias: '{account.alias}')")


@accounts.command(short_help="Create an account with a random mnemonic seed phrase")
@ape_cli_context()
@click.option("--hide-mnemonic", help="Hide the generated mnemonic", is_flag=True)
@click.option("--word-count", help="Words in the seed phrase", default=12, show_default=True)
@click.option("--hd-path", help="Derivation path", default=SOLANA_DEFAULT_PATH, show_default=True)
@non_existing_alias_argument()
def generate(cli_ctx, alias, hide_mnemonic, word_count, hd_path):
    show_mnemonic = not hide_mnemonic and click.confirm("Show mnemonic?", default=True)
    passphrase = prompt_for_new_passphrase()
    account, mnemonic = import_accounts_module().generate_account(
        alias, passphrase, hd_path=hd_path, word_count=word_count
    )
    if show_mnemonic:
        cli_ctx.logger.info(f"Newly generated mnemonic is: {click.style(mnemonic, bold=True)}")

    cli_ctx.logger.success(
        f"A new account '{account.address}' has been added with the id '{alias}'"
    )


@accounts.command(name="import", short_help="Import an account by secret key, seed phrase or file")
@ape_cli_context()
@click.option("--use-mnemonic", "use_mnemonic", help="Import from a mnemonic", is_flag=True)
@click.option(
    "--keypair-file",
    help="Import a solana-keygen keypair file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--hd-path", help="Derivation path", default=SOLANA_DEFAULT_PATH, show_default=True)
@non_existing_alias_argument()
def import_account(cli_ctx, alias, use_mnemonic, keypair_file, hd_path):
    accounts_module = import_accounts_module()
    if use_mnemonic:
        mnemonic = click.prompt("Enter mnemonic seed phrase", hide_input=True)
        try:
            account = accounts_module.import_account_from_mnemonic(
                alias, prompt_for_new_passphrase(), mnemonic, hd_path=hd_path
            )
        except Exception as err:  # noqa: BLE001
            cli_ctx.abort(
                f"Seed phrase can't be imported: {str(err).replace(mnemonic, HIDDEN_MESSAGE)}"
            )

    elif keypair_file:
        try:
            account = accounts_module.import_account_from_keypair_file(
                alias, prompt_for_new_passphrase(), keypair_file
            )
        except Exception as err:  # noqa: BLE001
            cli_ctx.abort(f"Keypair file can't be imported: {err}")

    else:
        secret_key = click.prompt("Enter secret key (base58, hex or JSON array)", hide_input=True)
        try:
            account = accounts_module.import_account_from_private_key(
                alias, prompt_for_new_passphrase(), secret_key
            )
        except Exception as err:  # noqa: BLE001
            cli_ctx.abort(f"Key can't be imported: {str(err).replace(secret_key, HIDDEN_MESSAGE)}")

    cli_ctx.logger.success(
        f"A new account '{account.address}' has been added with the id '{alias}'"
    )


@accounts.command(short_help="Export an account secret key as base58")
@ape_cli_context()
@existing_alias_argument(account_type=is_solana_account)
def export(cli_ctx, alias):
    account = cli_ctx.account_manager.load(alias)
    passphrase = click.prompt("Enter password to decrypt account", hide_input=True)
    keypair = Keypair.from_seed(account._decrypt_keyfile(passphrase))
    cli_ctx.logger.success(
        f"Account {account.address} secret key: {click.style(str(keypair), bold=True)}"
    )


@accounts.command(short_help="Change the password of an existing account")
@ape_cli_context()
@existing_alias_argument(account_type=is_solana_account)
def change_password(cli_ctx, alias):
    cli_ctx.account_manager.load(alias).change_password()
    cli_ctx.logger.success(f"Password has been changed for account '{alias}'")


@accounts.command(short_help="Delete an existing account")
@ape_cli_context()
@existing_alias_argument(account_type=is_solana_account)
def delete(cli_ctx, alias):
    cli_ctx.account_manager.load(alias).delete()
    cli_ctx.logger.success(f"Account '{alias}' has been deleted")


@cli.command(cls=ConnectedProviderCommand, short_help="Request an airdrop on a test network")
@ape_cli_context()
@network_option(ecosystem=ECOSYSTEM_NAME)
@account_option(account_type=is_solana_account)
@click.option("--sol", "amount_sol", type=float, default=1.0, show_default=True)
def airdrop(cli_ctx, account, amount_sol):
    lamports = int(amount_sol * LAMPORTS_PER_SOL)
    transaction_id = account.request_airdrop(lamports)
    cli_ctx.logger.success(f"Airdropped {amount_sol} SOL to {account.address} ({transaction_id})")
