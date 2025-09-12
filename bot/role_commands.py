import discord
from discord.ext import commands
from discord import app_commands
import logging
from bot.utils import create_success_embed, create_error_embed, create_info_embed, get_rank_title_by_points, Colors

logger = logging.getLogger(__name__)

def setup_role_commands(bot, role_reward_manager):
    """Setup enhanced role reward management commands"""

    @bot.tree.command(name='assignrolepoints', description='Assign points to all users with a specific role (Admin only)')
    @app_commands.describe(
        role_id='The role ID to assign points to',
        points='Number of points to assign (can be negative)'
    )
    @app_commands.default_permissions(administrator=True)
    async def assign_role_points(interaction: discord.Interaction, role_id: str, points: int):
        """Enhanced role point assignment with better feedback"""
        try:
            # Defer response as this might take time
            await interaction.response.defer(ephemeral=True)

            # Validate and get the role
            try:
                role_id_int = int(role_id)
                role = interaction.guild.get_role(role_id_int)
            except ValueError:
                embed = create_error_embed(
                    "Invalid Role ID",
                    "Please provide a valid numeric role ID.",
                    "You can find role IDs by right-clicking on a role and selecting 'Copy ID' (Developer Mode required)."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            if not role:
                embed = create_error_embed(
                    "Role Not Found",
                    f"No role found with ID `{role_id}` in this server.",
                    "Please verify the role ID and try again."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Get all members with this role
            members_with_role = []
            total_guild_members = len(interaction.guild.members)

            logger.info(f"🔍 Checking role {role.name} (ID: {role_id}) - Guild has {total_guild_members} total members")

            for member in interaction.guild.members:
                if not member.bot and role in member.roles:
                    members_with_role.append(member)

            logger.info(f"✅ Found {len(members_with_role)} members with role {role.name}")

            if not members_with_role:
                embed = create_info_embed(
                    "No Members Found",
                    f"No non-bot members found with role **{role.name}**.",
                    fields=[
                        {"name": "Guild Statistics", "value": f"Total members: {total_guild_members}", "inline": True},
                        {"name": "Role Statistics", "value": f"Members with role: 0", "inline": True},
                        {"name": "Suggestion", "value": f"Try using `/checkrole role_id:{role_id}` to debug this.", "inline": False}
                    ]
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Process point assignment
            success_count = 0
            failed_members = []

            for member in members_with_role:
                success = await role_reward_manager.leaderboard_manager.update_points(
                    interaction.guild.id, member.id, points, member.display_name
                )
                if success:
                    success_count += 1
                else:
                    failed_members.append(member.display_name)

            # Trigger auto-update for all active leaderboard views
            await role_reward_manager.trigger_leaderboard_updates(interaction.guild.id)

            # Create comprehensive success embed
            action_type = "reward" if points > 0 else "penalty" if points < 0 else "adjustment"
            embed_func = create_success_embed if points >= 0 else create_info_embed
            embed = embed_func(
                "Role Points Assignment Complete",
                f"Successfully processed point assignment for role **{role.name}**",
                f"Points {action_type} applied to {success_count} members",
                [
                    {"name": "Assignment Details", "value": f"**Role:** {role.name}\n**Points per member:** {points:+,}\n**Total points distributed:** {points * success_count:+,}", "inline": False},
                    {"name": "Results Summary", "value": f"**Successful:** {success_count}\n**Failed:** {len(failed_members)}", "inline": True},
                    {"name": "Member Statistics", "value": f"**Target members:** {len(members_with_role)}\n**Guild total:** {total_guild_members}", "inline": True},
                    {"name": "Action Type", "value": f"Points {action_type}", "inline": True}
                ]
            )

            # Failed members (if any)
            if failed_members:
                failed_list = ", ".join(failed_members[:5])
                if len(failed_members) > 5:
                    failed_list += f" and {len(failed_members) - 5} more..."
                embed.add_field(
                    name="━━━━━━━━━ Failed Updates ━━━━━━━━━",
                    value=failed_list,
                    inline=False
                )

            embed.set_footer(text=f"Executed by {interaction.user.display_name}")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"❌ Error in assign_role_points: {e}")
            embed = create_error_embed(
                "Command Error",
                "An error occurred while assigning points to role members.",
                f"Error details: {str(e)}"
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name='checkrole', description='Check details about a specific role (Admin only)')
    @app_commands.describe(role_id='The role ID to check')
    @app_commands.default_permissions(administrator=True)
    async def check_role(interaction: discord.Interaction, role_id: str):
        """Check role details and member count"""
        try:
            await interaction.response.defer(ephemeral=True)

            # Validate role ID
            try:
                role_id_int = int(role_id)
                role = interaction.guild.get_role(role_id_int)
            except ValueError:
                embed = create_error_embed(
                    "Invalid Role ID",
                    "Please provide a valid numeric role ID."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            if not role:
                embed = create_error_embed(
                    "Role Not Found",
                    f"No role found with ID `{role_id}` in this server."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Count members with this role
            members_with_role = [member for member in interaction.guild.members if not member.bot and role in member.roles]
            bot_members_with_role = [member for member in interaction.guild.members if member.bot and role in member.roles]

            # Gather role properties
            properties = []
            if role.hoist:
                properties.append("**Displayed separately:** Yes")
            if role.mentionable:
                properties.append("**Mentionable:** Yes")
            if role.managed:
                properties.append("**Managed by integration:** Yes")
            if role.permissions.administrator:
                properties.append("**Administrator:** Yes")

            # Create detailed role information embed
            embed = create_info_embed(
                f"Role Information: {role.name}",
                f"Detailed information about the {role.name} role",
                f"Role ID: {role.id} | Position: {role.position}",
                [
                    {"name": "Basic Information", "value": f"**Name:** {role.name}\n**ID:** {role.id}\n**Mention:** {role.name}\n**Position:** {role.position}", "inline": False},
                    {"name": "Member Statistics", "value": f"**Non-bot members:** {len(members_with_role)}\n**Bot members:** {len(bot_members_with_role)}\n**Total members:** {len(members_with_role) + len(bot_members_with_role)}", "inline": True},
                    {"name": "Properties", "value": "\n".join(properties) if properties else "No special properties", "inline": True}
                ]
            )

            # Show some member examples (up to 10)
            if members_with_role:
                member_list = [member.display_name for member in members_with_role[:10]]
                if len(members_with_role) > 10:
                    member_list.append(f"... and {len(members_with_role) - 10} more")
                
                embed.add_field(
                    name="━━━━━━━━━ Sample Members ━━━━━━━━━",
                    value="\n".join(member_list),
                    inline=False
                )

            # Color info
            if role.color != discord.Color.default():
                embed.add_field(
                    name="━━━━━━━━━ Color ━━━━━━━━━",
                    value=f"**Hex:** {str(role.color)}\n**RGB:** {role.color.to_rgb()}",
                    inline=True
                )

            embed.set_footer(text=f"Requested by {interaction.user.display_name}")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"❌ Error in check_role: {e}")
            embed = create_error_embed(
                "Command Error",
                "An error occurred while checking role information."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name='roleconfig', description='Configure automatic role rewards (Admin only)')
    @app_commands.describe(
        role='The role to configure rewards for',
        points_per_day='Points awarded daily for having this role (0 to disable)',
        interval_hours='How often to give rewards in hours (default: 24)'
    )
    @app_commands.default_permissions(administrator=True)
    async def configure_role_rewards(interaction: discord.Interaction, role: discord.Role, 
                                   points_per_day: int, interval_hours: int = 24):
        """Configure automatic role reward system"""
        try:
            await interaction.response.defer(ephemeral=True)

            guild_id = interaction.guild.id

            if points_per_day == 0:
                # Remove role reward
                success = await role_reward_manager.remove_role_reward(guild_id, role.id)
                if success:
                    embed = create_success_embed(
                        "Role Reward Removed",
                        f"Automatic rewards for {role.mention} have been disabled."
                    )
                else:
                    embed = create_info_embed(
                        "No Change",
                        f"Role {role.mention} was not configured for automatic rewards."
                    )
            else:
                # Add/update role reward
                await role_reward_manager.add_role_reward(guild_id, role.id, points_per_day)
                await role_reward_manager.set_reward_interval(guild_id, interval_hours)

                embed = create_success_embed(
                    "Role Reward Configured",
                    f"Members with {role.mention} will now receive {points_per_day} points every {interval_hours} hours."
                )

                embed.add_field(
                    name="━━━━━━━━━ Configuration Details ━━━━━━━━━",
                    value=f"**Role:** {role.name}\n**Points per interval:** {points_per_day}\n**Interval:** {interval_hours} hours",
                    inline=False
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"❌ Error in configure_role_rewards: {e}")
            embed = create_error_embed(
                "Configuration Error",
                "An error occurred while configuring role rewards."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @bot.tree.command(name='listroles', description='List all roles in the server with member counts (Admin only)')
    @app_commands.default_permissions(administrator=True)
    async def list_roles(interaction: discord.Interaction):
        """List all roles in the server"""
        try:
            await interaction.response.defer(ephemeral=True)

            guild = interaction.guild
            roles_info = []

            # Get role information
            for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
                if role.name == "@everyone":
                    continue  # Skip everyone role

                member_count = len([m for m in role.members if not m.bot])
                bot_count = len([m for m in role.members if m.bot])
                
                roles_info.append({
                    'role': role,
                    'member_count': member_count,
                    'bot_count': bot_count,
                    'total_count': member_count + bot_count
                })

            # Prepare role fields for the embed
            role_fields = []
            chunk_size = 20
            for i in range(0, len(roles_info), chunk_size):
                chunk = roles_info[i:i + chunk_size]
                
                role_list = []
                for info in chunk:
                    role = info['role']
                    prefix = "Bot role:" if info['member_count'] == 0 and info['bot_count'] > 0 else ""
                    role_list.append(f"{prefix} {role.name} - {info['member_count']} members")

                field_name = f"Roles {i+1}-{min(i+chunk_size, len(roles_info))}"
                role_fields.append({
                    "name": field_name,
                    "value": "\n".join(role_list) if role_list else "No roles",
                    "inline": True
                })

            # Create embed using standardized function
            embed = create_info_embed(
                f"Roles in {guild.name}",
                "Complete overview of server roles and member distribution",
                f"Total roles: {len(roles_info)}",
                role_fields
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"❌ Error in list_roles: {e}")
            embed = create_error_embed(
                "Command Error",
                "An error occurred while listing roles."
            )
            await interaction.followup.send(embed=embed, ephemeral=True)