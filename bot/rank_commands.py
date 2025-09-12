import discord
from discord.ext import commands
from discord import app_commands
from bot.utils import create_error_embed, create_success_embed, SPECIAL_ROLES
from bot.permissions import has_admin_permission
from typing import Optional
import asyncio


class RankCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rank_manager = None

    async def cog_load(self):
        """Initialize rank manager when cog loads"""
        pass  # Will be initialized in get_rank_manager()

    async def get_rank_manager(self):
        """Get or create rank manager instance"""
        if not self.rank_manager and hasattr(self.bot, 'sql_database') and self.bot.sql_database:
            from bot.rank_manager import RankManager
            self.rank_manager = RankManager(self.bot.sql_database)
            # Initialize tables asynchronously
            if not getattr(self.rank_manager, '_initialized', False):
                asyncio.create_task(self.rank_manager.initialize_tables())
        return self.rank_manager

    @app_commands.command(name="highrankmember", description="Display all members with high rank roles")
    async def high_rank_member(self, interaction: discord.Interaction):
        """Show all high rank members in the server"""
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        rank_manager = await self.get_rank_manager()
        if not rank_manager:
            embed = create_error_embed("System Error", "Rank management system not initialized.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get all high rank roles in this guild
        high_rank_roles = rank_manager.get_high_rank_roles_for_guild(interaction.guild)

        if not high_rank_roles:
            embed = create_error_embed("No High Ranks", "No high rank roles found in this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 High Rank Members",
            description="Current members with high rank roles",
            color=0x4B0082
        )

        total_members = 0
        for role in sorted(high_rank_roles, key=lambda r: list(SPECIAL_ROLES.keys()).index(r.id)):
            member_list = []
            if role.members:
                for member in role.members:
                    member_list.append(f"• {member.display_name}")
                    total_members += 1

            # Get role limits if any
            limit = await rank_manager.get_role_limit(interaction.guild.id, role.id)
            current_count = len(role.members)
            
            # Format the field name with limit info
            if limit:
                status_icon = "🔒" if current_count >= limit else "🟢"
                field_name = f"{role.name} ({current_count}/{limit}) {status_icon}"
            else:
                field_name = f"{role.name} ({current_count})"

            embed.add_field(
                name=field_name,
                value="\n".join(member_list) if member_list else "No members",
                inline=False
            )

        if total_members == 0:
            embed.add_field(
                name="Status",
                value="No members currently have high rank roles.",
                inline=False
            )

        embed.set_footer(text=f"Total high rank members: {total_members}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="limitrole", description="Set member limit for high rank roles")
    @app_commands.describe(
        role="Select the high rank role to limit",
        limit="Maximum number of members allowed (1-50)"
    )
    async def limit_role(self, interaction: discord.Interaction, role: discord.Role, limit: int):
        """Set member limit for a high rank role"""
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not has_admin_permission(interaction.user, interaction.guild):
            embed = create_error_embed("Permission Denied", "You need admin permissions to use this command.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        rank_manager = await self.get_rank_manager()
        if not rank_manager:
            embed = create_error_embed("System Error", "Rank management system not initialized.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if it's a high rank role
        if not rank_manager.is_high_rank_role(role.id):
            embed = create_error_embed("Invalid Role", f"{role.name} is not a high rank role that can be limited.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Validate limit
        if limit < 1 or limit > 50:
            embed = create_error_embed("Invalid Limit", "Limit must be between 1 and 50.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Set the limit
        success = await rank_manager.set_role_limit(interaction.guild.id, role.id, limit)
        if not success:
            embed = create_error_embed("Database Error", "Failed to set role limit.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if current members exceed limit
        current_count = await rank_manager.get_role_holders_count(interaction.guild, role.id)

        embed = create_success_embed(
            "Role Limit Set",
            f"**{role.name}** is now limited to **{limit}** members.\n"
            f"Current members: **{current_count}**"
        )

        # If over limit, warn about enforcement
        if current_count > limit:
            embed.add_field(
                name="⚠️ Over Limit",
                value=f"This role currently has {current_count} members, which exceeds the new limit of {limit}. "
                      f"The newest {current_count - limit} member(s) will be automatically removed when new assignments occur.",
                inline=False
            )

        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="viewlimits", description="View current role limits")
    async def view_limits(self, interaction: discord.Interaction):
        """Display current role limits"""
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        rank_manager = await self.get_rank_manager()
        if not rank_manager:
            embed = create_error_embed("System Error", "Rank management system not initialized.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        role_limits = await rank_manager.get_all_role_limits(interaction.guild.id)

        if not role_limits:
            embed = create_error_embed("No Limits", "No role limits have been set for this server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="📊 Role Limits",
            description="Current member limits for high rank roles",
            color=0x3498DB
        )

        for role_id, limit in role_limits.items():
            role = interaction.guild.get_role(role_id)
            if role:
                current_count = await rank_manager.get_role_holders_count(interaction.guild, role_id)
                status = "🔒 FULL" if current_count >= limit else "🟢 Available"
                embed.add_field(
                    name=f"{role.name}",
                    value=f"Limit: {limit}\nCurrent: {current_count}\nStatus: {status}",
                    inline=True
                )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="removelimit", description="Remove member limit from a role")
    @app_commands.describe(role="Select the role to remove limit from")
    async def remove_limit(self, interaction: discord.Interaction, role: discord.Role):
        """Remove member limit from a role"""
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not has_admin_permission(interaction.user, interaction.guild):
            embed = create_error_embed("Permission Denied", "You need admin permissions to use this command.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        rank_manager = await self.get_rank_manager()
        if not rank_manager:
            embed = create_error_embed("System Error", "Rank management system not initialized.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if role has a limit
        current_limit = await rank_manager.get_role_limit(interaction.guild.id, role.id)
        if not current_limit:
            embed = create_error_embed("No Limit", f"{role.name} does not have a member limit set.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Remove the limit
        success = await rank_manager.remove_role_limit(interaction.guild.id, role.id)
        if not success:
            embed = create_error_embed("Database Error", "Failed to remove role limit.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = create_success_embed(
            "Limit Removed",
            f"Member limit has been removed from **{role.name}**.\n"
            f"This role can now have unlimited members."
        )

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(RankCommands(bot))