import io
import os
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands


# -----------------------------
# Configuration via variables d'environnement
# -----------------------------
# Obligatoire
TOKEN ="MTQ3NDUwNDc1NTU3NjU3NDA0NA.G54VGO.lQPIfi36aTJnUAwrjLMSFoz7gJvWnlX4vIDQm4"

# Optionnel (pour sync rapide des slash commands sur un serveur de test)
TEST_GUILD_ID = int(os.getenv("1465312411484688529", "0"))

# IDs Discord (optionnels mais recommandes)
TICKET_CATEGORY_ID = int(os.getenv("1470155712683311360", "0"))
TRANSCRIPT_CHANNEL_ID = int(os.getenv("1474727407956262974", "0"))
ADMIN_ROLE_ID = int(os.getenv("1470132349994926221", "0"))
MOD_ROLE_ID = int(os.getenv("1470156413165900081", "0"))


intents = discord.Intents.default()
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
is_synced = False


def is_staff(member: discord.Member) -> bool:
    role_ids = {rid for rid in (ADMIN_ROLE_ID, MOD_ROLE_ID) if rid}
    if not role_ids:
        return member.guild_permissions.manage_channels or member.guild_permissions.administrator
    member_role_ids = {role.id for role in member.roles}
    return bool(member_role_ids.intersection(role_ids))


def resolve_ticket_category(guild: discord.Guild) -> discord.CategoryChannel | None:
    if TICKET_CATEGORY_ID:
        chan = guild.get_channel(TICKET_CATEGORY_ID)
        if isinstance(chan, discord.CategoryChannel):
            return chan
    for name in ("ticket", "tickets", "ticekt", "recrutement-ticket"):
        found = discord.utils.get(guild.categories, name=name)
        if found:
            return found
    return None


async def build_transcript(channel: discord.TextChannel) -> io.BytesIO:
    lines = []
    async for message in channel.history(limit=None, oldest_first=True):
        created = message.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        content = message.content or ""
        attachments = " ".join(att.url for att in message.attachments)
        embeds = " [embed]" if message.embeds else ""
        line = f"[{created}] {message.author} : {content} {attachments}{embeds}".rstrip()
        lines.append(line)

    if not lines:
        lines.append("Aucun message dans le ticket.")

    payload = "\n".join(lines).encode("utf-8")
    return io.BytesIO(payload)


class StaffDecisionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.success, custom_id="recruit_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Candidature acceptee",
            description=f"Decision prise par {interaction.user.mention}",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger, custom_id="recruit_refuse")
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Candidature refusee",
            description=f"Decision prise par {interaction.user.mention}",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        await interaction.response.send_message(embed=embed)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Prendre le ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Commande invalide ici.", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission.", ephemeral=True)
            return

        claimed_by = None
        if channel.topic and channel.topic.startswith("claimed_by:"):
            try:
                claimed_by = int(channel.topic.split(":", 1)[1])
            except ValueError:
                claimed_by = None

        if claimed_by and interaction.guild:
            user = interaction.guild.get_member(claimed_by)
            if user:
                await interaction.response.send_message(
                    f"Ce ticket est deja pris en charge par {user.mention}.",
                    ephemeral=True,
                )
                return

        await channel.edit(topic=f"claimed_by:{interaction.user.id}")
        await interaction.response.send_message(f"Ticket pris en charge par {interaction.user.mention}.")

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Commande invalide ici.", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
            await interaction.response.send_message("Tu n'as pas la permission de fermer ce ticket.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # Transcription automatique
        transcript_channel = interaction.guild.get_channel(TRANSCRIPT_CHANNEL_ID) if interaction.guild else None
        transcript_file = await build_transcript(channel)
        filename = f"transcript-{channel.name}.txt"

        if isinstance(transcript_channel, discord.TextChannel):
            file = discord.File(fp=transcript_file, filename=filename)
            info = (
                f"Ticket ferme par {interaction.user.mention}\n"
                f"Serveur: {interaction.guild.name}\n"
                f"Canal: {channel.name}"
            )
            await transcript_channel.send(content=info, file=file)

        await channel.delete(reason=f"Ticket ferme par {interaction.user}")


class RecruitmentFormModal(discord.ui.Modal, title="Formulaire de recrutement"):
    nom_rp = discord.ui.TextInput(label="Nom Prenom RP", placeholder="Ex: Jean Dupont", max_length=100)
    age_irl = discord.ui.TextInput(label="Age IRL", placeholder="Ex: 19", max_length=3)
    role_voulu = discord.ui.TextInput(label="Role souhaite", placeholder="Ex: AED / Prof / CPE", max_length=50)
    motivation = discord.ui.TextInput(label="Motivation", style=discord.TextStyle.paragraph, max_length=1000)
    qualites_defauts = discord.ui.TextInput(
        label="Qualites / Defauts",
        style=discord.TextStyle.paragraph,
        placeholder="Ex: Qualites: ... | Defauts: ...",
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Ce formulaire doit etre utilise sur un serveur.", ephemeral=True)
            return

        guild = interaction.guild
        category = resolve_ticket_category(guild)

          
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                read_message_history=True,
            ),
        }

        for role_id in (ADMIN_ROLE_ID, MOD_ROLE_ID):
            if role_id:
                role = guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        manage_channels=True,
                        manage_messages=True,
                    )

        base_name = f"recrut-{interaction.user.name}".lower().replace(" ", "-")
        channel = await guild.create_text_channel(
            name=base_name[:90],
            category=category,
            overwrites=overwrites,
            reason="Ouverture ticket recrutement",
        )

        embed = discord.Embed(
            title="Nouvelle candidature School RP",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Candidat", value=interaction.user.mention, inline=False)
        embed.add_field(name="Nom Prenom RP", value=str(self.nom_rp), inline=False)
        embed.add_field(name="Age IRL", value=str(self.age_irl), inline=True)
        embed.add_field(name="Role souhaite", value=str(self.role_voulu), inline=True)
        embed.add_field(name="Motivation", value=str(self.motivation), inline=False)
        embed.add_field(name="Qualites / Defauts", value=str(self.qualites_defauts), inline=False)
        embed.set_footer(text="Utilisez les boutons pour accepter/refuser puis fermer le ticket.")

        ping_roles = []
        for role_id in (ADMIN_ROLE_ID, MOD_ROLE_ID):
            if role_id:
                role = guild.get_role(role_id)
                if role:
                    ping_roles.append(role.mention)

        await channel.send(
            content=(" ".join(ping_roles) + "\n" if ping_roles else "") + f"Ticket de {interaction.user.mention}",
            embed=embed,
            view=StaffDecisionView(),
        )
        await channel.send("Controle du ticket:", view=TicketControlView())

        await interaction.response.send_message(
            f"Ticket cree: {channel.mention}",
            ephemeral=True,
        )


class RecruitmentPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ouvrir un ticket recrutement", style=discord.ButtonStyle.primary, custom_id="open_recruit_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RecruitmentFormModal())


class RecruitmentBot(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.bot = client

    @app_commands.command(name="recrutement", description="Envoie le panneau de ticket recrutement")
    @app_commands.default_permissions(administrator=True)
    async def recrutement_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Recrutement Collége Jules Ferry",
            description=(
                "Clique sur le bouton pour ouvrir un ticket.\n"
                "Tu devras remplir un formulaire avant la creation du ticket."
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, view=RecruitmentPanelView())


@bot.event
async def on_ready():
    global is_synced
    if not is_synced:
        if TEST_GUILD_ID:
            guild_obj = discord.Object(id=TEST_GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"Slash commands synchronisees sur TEST_GUILD_ID={TEST_GUILD_ID}: {len(synced)}")
        else:
            synced = await bot.tree.sync()
            print(f"Slash commands globales synchronisees: {len(synced)}")
        is_synced = True
    print(f"Connecte en tant que {bot.user} (ID: {bot.user.id})")


async def setup_persistent_views():
    bot.add_view(RecruitmentPanelView())
    bot.add_view(TicketControlView())
    bot.add_view(StaffDecisionView())


async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN est manquant. Configure la variable d'environnement.")

    await bot.add_cog(RecruitmentBot(bot))
    await setup_persistent_views()

    await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
