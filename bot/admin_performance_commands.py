import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Dict

logger = logging.getLogger(__name__)

class AdminPerformanceCommands(commands.Cog):
    """Admin commands for monitoring bot performance"""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="performance_report", description="Get comprehensive bot performance report (Admin only)")
    async def performance_report(self, interaction: discord.Interaction):
        """Display detailed performance metrics"""
        try:
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ This command requires administrator permissions.", ephemeral=True)
                return

            await interaction.response.defer()

            # Get performance data
            performance_data = {}
            memory_data = {}
            database_data = {}

            if hasattr(self.bot, 'performance_monitor'):
                performance_data = self.bot.performance_monitor.get_performance_report()

            if hasattr(self.bot, 'memory_manager'):
                memory_data = self.bot.memory_manager.get_memory_stats()

            if hasattr(self.bot, 'database_optimizer'):
                database_data = await self.bot.database_optimizer.get_table_sizes()

            # Create comprehensive embed
            embed = discord.Embed(
                title="🔍 Bot Performance Report",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )

            # Performance metrics
            if performance_data:
                embed.add_field(
                    name="📊 System Performance",
                    value=(
                        f"**Uptime:** {performance_data.get('uptime', 'N/A')}\n"
                        f"**Commands Executed:** {performance_data.get('commands_executed', 0):,}\n"
                        f"**Commands/Minute:** {performance_data.get('commands_per_minute', 0):.1f}\n"
                        f"**Avg Response Time:** {performance_data.get('avg_response_time', 'N/A')}\n"
                        f"**Error Count:** {performance_data.get('error_count', 0)}"
                    ),
                    inline=True
                )

                embed.add_field(
                    name="💾 Resource Usage",
                    value=(
                        f"**Memory Usage:** {performance_data.get('avg_memory_usage', 'N/A')}\n"
                        f"**CPU Usage:** {performance_data.get('avg_cpu_usage', 'N/A')}\n"
                        f"**Cache Hit Rate:** {performance_data.get('cache_hit_rate', 'N/A')}\n"
                        f"**Active Views:** {performance_data.get('active_views', 0)}"
                    ),
                    inline=True
                )

            # Memory management
            if memory_data:
                embed.add_field(
                    name="🧹 Memory Management",
                    value=(
                        f"**Memory Usage:** {memory_data.get('memory_usage_mb', 0):.1f} MB\n"
                        f"**Memory Percent:** {memory_data.get('memory_percent', 0):.1f}%\n"
                        f"**Active Views:** {memory_data.get('active_views', 0)}\n"
                        f"**GC Objects:** {memory_data.get('gc_objects', 0):,}"
                    ),
                    inline=True
                )

            # Database performance
            if performance_data and performance_data.get('database_queries'):
                embed.add_field(
                    name="🗄️ Database Performance",
                    value=(
                        f"**Total Queries:** {performance_data.get('database_queries', 0):,}\n"
                        f"**Queries/Minute:** {(performance_data.get('database_queries', 0) / max(1, performance_data.get('commands_executed', 1) / max(1, performance_data.get('commands_per_minute', 1)))):.1f}"
                    ),
                    inline=True
                )

            # Top database tables by size
            if database_data:
                top_tables = list(database_data.items())[:5]
                if top_tables:
                    embed.add_field(
                        name="📈 Largest Database Tables",
                        value="\n".join([f"**{table}:** {size}" for table, size in top_tables]),
                        inline=False
                    )

            # Add health status
            health_status = "🟢 Healthy"
            if performance_data:
                if float(performance_data.get('avg_memory_usage', '0%').replace('%', '')) > 85:
                    health_status = "🔴 High Memory Usage"
                elif float(performance_data.get('avg_cpu_usage', '0%').replace('%', '')) > 80:
                    health_status = "🟡 High CPU Usage"
                elif performance_data.get('error_count', 0) > 10:
                    health_status = "🟡 High Error Rate"

            embed.add_field(
                name="🏥 Health Status",
                value=health_status,
                inline=False
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"❌ Error in performance report command: {e}")
            embed = discord.Embed(
                title="Error",
                description="Failed to generate performance report.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="memory_cleanup", description="Force memory cleanup (Admin only)")
    async def memory_cleanup(self, interaction: discord.Interaction):
        """Force memory cleanup"""
        try:
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ This command requires administrator permissions.", ephemeral=True)
                return

            await interaction.response.defer()

            # Perform cleanup
            if hasattr(self.bot, 'memory_manager'):
                await self.bot.memory_manager.emergency_cleanup()

                # Get updated stats
                stats = self.bot.memory_manager.get_memory_stats()

                embed = discord.Embed(
                    title="🧹 Memory Cleanup Complete",
                    color=discord.Color.green()
                )

                embed.add_field(
                    name="Updated Memory Stats",
                    value=(
                        f"**Memory Usage:** {stats.get('memory_usage_mb', 0):.1f} MB\n"
                        f"**Active Views:** {stats.get('active_views', 0)}\n"
                        f"**GC Objects:** {stats.get('gc_objects', 0):,}"
                    ),
                    inline=False
                )
            else:
                embed = discord.Embed(
                    title="⚠️ Memory Manager Not Available",
                    description="Memory management system is not initialized.",
                    color=discord.Color.orange()
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"❌ Error in memory cleanup command: {e}")

    @app_commands.command(name="database_optimize", description="Optimize database performance (Admin only)")
    async def database_optimize(self, interaction: discord.Interaction):
        """Optimize database performance"""
        try:
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ This command requires administrator permissions.", ephemeral=True)
                return

            await interaction.response.defer()

            if not hasattr(self.bot, 'database_optimizer'):
                embed = discord.Embed(
                    title="⚠️ Database Optimizer Not Available",
                    description="Database optimization system is not initialized.",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)
                return

            # Perform optimization
            embed = discord.Embed(
                title="🔧 Database Optimization in Progress",
                description="Optimizing database performance...",
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed)

            # Run optimization tasks
            await self.bot.database_optimizer.analyze_table_statistics()
            await self.bot.database_optimizer.vacuum_database()

            # Get table sizes after optimization
            table_sizes = await self.bot.database_optimizer.get_table_sizes()

            # Update embed
            embed = discord.Embed(
                title="✅ Database Optimization Complete",
                color=discord.Color.green()
            )

            if table_sizes:
                top_tables = list(table_sizes.items())[:5]
                embed.add_field(
                    name="Top Tables by Size",
                    value="\n".join([f"**{table}:** {size}" for table, size in top_tables]),
                    inline=False
                )

            embed.add_field(
                name="Completed Tasks",
                value="✅ Table statistics updated\n✅ Database vacuum completed\n✅ Query optimization applied",
                inline=False
            )

            await interaction.edit_original_response(embed=embed)

        except Exception as e:
            logger.error(f"❌ Error in database optimize command: {e}")
            embed = discord.Embed(
                title="❌ Database Optimization Failed",
                description=f"An error occurred during optimization: {str(e)[:200]}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="starter_quest_status", description="Check starter quest completion status for all members (Admin only)")
    @app_commands.describe(
        show_details="Show detailed breakdown of each member's status"
    )
    @app_commands.default_permissions(administrator=True)
    async def starter_quest_status(self, interaction: discord.Interaction, show_details: bool = False):
        """Check starter quest completion status for all server members"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            await interaction.response.defer()

            # Get all current members (excluding bots)
            current_members = [member for member in interaction.guild.members if not member.bot]

            # Analysis counters
            total_members = len(current_members)
            completed_both_starter = 0
            completed_partial_starter = 0
            no_starter_progress = 0
            has_mentor = 0
            no_welcome_record = 0

            # Detailed tracking
            detailed_status = []

            async with self.bot.database.pool.acquire() as conn:
                for member in current_members:
                    try:
                        # Check welcome automation record
                        welcome_record = await conn.fetchrow('''
                            SELECT starter_quest_1, starter_quest_2, mentor_id, 
                                   quest_1_completed, quest_2_completed, new_disciple_role_awarded
                            FROM welcome_automation 
                            WHERE user_id = $1 AND guild_id = $2
                        ''', member.id, interaction.guild.id)

                        if not welcome_record:
                            no_welcome_record += 1
                            if show_details:
                                detailed_status.append({
                                    'member': member.display_name,
                                    'status': 'No welcome record',
                                    'details': 'Not processed by welcome system'
                                })
                            continue

                        # Check if they have a mentor
                        if welcome_record['mentor_id']:
                            has_mentor += 1
                            if show_details:
                                detailed_status.append({
                                    'member': member.display_name,
                                    'status': 'Has mentor',
                                    'details': 'Exempt from starter quests'
                                })
                            continue

                        # Check starter quest completion from quest_progress table
                        starter_completions = await conn.fetch('''
                            SELECT quest_id, status FROM quest_progress 
                            WHERE user_id = $1 AND guild_id = $2 
                            AND quest_id LIKE 'starter%'
                            AND status = 'approved'
                        ''', member.id, interaction.guild.id)

                        completed_starter_ids = [row['quest_id'] for row in starter_completions]

                        # Get assigned starter quests
                        assigned_quests = []
                        if welcome_record['starter_quest_1']:
                            assigned_quests.append(welcome_record['starter_quest_1'])
                        if welcome_record['starter_quest_2']:
                            assigned_quests.append(welcome_record['starter_quest_2'])

                        # Determine completion status
                        completed_count = sum(1 for quest_id in assigned_quests if quest_id in completed_starter_ids)

                        if completed_count == len(assigned_quests) and len(assigned_quests) > 0:
                            completed_both_starter += 1
                            status = 'Completed all assigned'
                            details = f"Completed {completed_count}/{len(assigned_quests)} starter quests"
                        elif completed_count > 0:
                            completed_partial_starter += 1
                            status = 'Partially completed'
                            details = f"Completed {completed_count}/{len(assigned_quests)} starter quests"
                        else:
                            no_starter_progress += 1
                            status = 'No progress'
                            details = f"Assigned {len(assigned_quests)} starter quests, completed none"

                        if show_details:
                            detailed_status.append({
                                'member': member.display_name,
                                'status': status,
                                'details': details
                            })

                    except Exception as e:
                        logger.error(f"❌ Error checking starter quest status for {member.id}: {e}")

            # Calculate completion percentage
            mentorless_members = total_members - has_mentor - no_welcome_record
            completion_rate = (completed_both_starter / mentorless_members * 100) if mentorless_members > 0 else 0

            # Create summary embed
            from bot.utils import create_info_embed
            embed = create_info_embed(
                "📊 Starter Quest Completion Analysis",
                f"Analysis of {total_members} server members (excluding bots)",
                f"**Completion Rate:** {completion_rate:.1f}% of eligible members"
            )

            # Add statistics
            embed.add_field(
                name="━━━━━━━━━ Completion Summary ━━━━━━━━━",
                value=(
                    f"**✅ Fully Completed:** {completed_both_starter} members\n"
                    f"**🔄 Partially Completed:** {completed_partial_starter} members\n"
                    f"**❌ No Progress:** {no_starter_progress} members\n"
                    f"**👨‍🏫 Has Mentor:** {has_mentor} members (exempt)\n"
                    f"**❓ No Welcome Record:** {no_welcome_record} members"
                ),
                inline=False
            )

            # Add breakdown
            embed.add_field(
                name="━━━━━━━━━ Member Categories ━━━━━━━━━",
                value=(
                    f"**Total Members:** {total_members}\n"
                    f"**Eligible for Starter Quests:** {mentorless_members}\n"
                    f"**Mentored Members:** {has_mentor}\n"
                    f"**Unprocessed Members:** {no_welcome_record}"
                ),
                inline=False
            )

            # Add recommendations
            if no_starter_progress > 0:
                embed.add_field(
                    name="━━━━━━━━━ Recommendations ━━━━━━━━━",
                    value=(
                        f"**Action Required:** {no_starter_progress} members need starter quest completion\n"
                        f"**Command:** Use `/bulk_submit_starter` to help members get started\n"
                        f"**Follow-up:** Consider reaching out to inactive members directly"
                    ),
                    inline=False
                )

            await interaction.followup.send(embed=embed, ephemeral=False)

            # Send detailed breakdown if requested
            if show_details and detailed_status:
                # Split into chunks of 10 for readability
                chunk_size = 10
                for i in range(0, len(detailed_status), chunk_size):
                    chunk = detailed_status[i:i + chunk_size]

                    detail_embed = create_info_embed(
                        f"📋 Detailed Status (Part {i//chunk_size + 1})",
                        f"Individual member breakdown",
                        f"Showing members {i+1}-{min(i+chunk_size, len(detailed_status))} of {len(detailed_status)}"
                    )

                    status_text = ""
                    for item in chunk:
                        status_text += f"**{item['member']}**\n└ {item['status']}: {item['details']}\n\n"

                    detail_embed.add_field(
                        name="Member Status Details",
                        value=status_text[:1024],  # Discord field limit
                        inline=False
                    )

                    await interaction.followup.send(embed=detail_embed, ephemeral=False)

            logger.info(f"✅ Starter quest analysis completed by {interaction.user.display_name}")

        except Exception as e:
            logger.error(f"❌ Error in starter_quest_status: {e}")
            from bot.utils import create_error_embed
            embed = create_error_embed("Analysis Failed", f"An error occurred: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="bulk_approve_quests", description="Bulk approve all pending quest submissions (Admin only)")
    @app_commands.describe(
        confirm="Type 'APPROVE ALL' to confirm this action"
    )
    @app_commands.default_permissions(administrator=True)
    async def bulk_approve_quests(self, interaction: discord.Interaction, confirm: str):
        """Bulk approve all pending quest submissions"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Check confirmation text
            if confirm != "APPROVE ALL":
                embed = create_error_embed(
                    "Confirmation Required",
                    "To bulk approve all quests, you must type exactly: `APPROVE ALL`",
                    "This action will approve ALL pending quest submissions!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            await interaction.response.defer()

            # Get all pending approvals
            quest_cog = self.bot.get_cog('UnifiedBotCommands')
            if not quest_cog:
                from bot.utils import create_error_embed
                embed = create_error_embed(
                    "System Error",
                    "Quest system not available",
                    "Please try again later or contact an administrator."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            pending_approvals = await quest_cog.quest_manager.get_pending_approvals(interaction.guild.id)

            if not pending_approvals:
                from bot.utils import create_info_embed
                embed = create_info_embed(
                    "No Pending Approvals",
                    "There are currently no quest submissions waiting for approval.",
                    "All submitted quests have been processed!"
                )
                await interaction.followup.send(embed=embed, ephemeral=False)
                return

            approved_count = 0
            errors = 0
            quest_manager = quest_cog.quest_manager
            leaderboard_manager = quest_cog.leaderboard_manager

            async with quest_manager.database.pool.acquire() as conn:
                for approval in pending_approvals:
                    try:
                        quest_id = approval['quest_id']
                        user_id = approval['user_id']

                        # Get quest details
                        quest = await quest_manager.get_quest(quest_id)
                        if not quest:
                            continue

                        # Approve the quest
                        progress = await quest_manager.approve_quest(quest_id, user_id, interaction.user.id)
                        if not progress:
                            continue

                        # Extract points from reward or use default
                        if quest.reward:
                            award_points = quest_cog._extract_points_from_reward(quest.reward)
                        else:
                            award_points = 10

                        # Award points
                        await leaderboard_manager.add_points(
                            interaction.guild.id, user_id, award_points, ""
                        )

                        # Update user stats
                        user_stats_manager = quest_cog.user_stats_manager
                        await user_stats_manager.update_quest_completed(user_id, interaction.guild.id)

                        approved_count += 1

                    except Exception as e:
                        logger.error(f"❌ Error bulk approving quest {approval.get('quest_id', 'unknown')}: {e}")
                        errors += 1

            # Update all active leaderboards
            from bot.commands import update_active_leaderboards
            await update_active_leaderboards(interaction.guild.id)

            # Send results
            from bot.utils import create_success_embed
            embed = create_success_embed(
                "Bulk Approval Complete",
                f"Successfully approved {approved_count} quest submissions",
                f"**Approved:** {approved_count} quests\n**Errors:** {errors} failed\n**Total Processed:** {len(pending_approvals)}"
            )

            await interaction.followup.send(embed=embed, ephemeral=False)
            logger.info(f"✅ Bulk approved {approved_count} quests by {interaction.user.display_name}")

        except Exception as e:
            logger.error(f"❌ Error in bulk_approve_quests: {e}")
            from bot.utils import create_error_embed
            embed = create_error_embed("Bulk Approval Failed", f"An error occurred: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="bulk_submit_starters", description="Mark all current members as having submitted starter quests (Admin only)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        confirm="Type 'CONFIRM' to proceed with bulk submission"
    )
    async def bulk_submit_starters(self, interaction: discord.Interaction, confirm: str = ""):
        """Mark all current server members as having submitted their starter quests for manual approval"""
        try:
            if confirm.upper() != "CONFIRM":
                from bot.utils import create_error_embed
                embed = create_error_embed(
                    "Confirmation Required",
                    "This will mark ALL current server members as having submitted starter quests.",
                    "Use `/bulk_submit_starters confirm:CONFIRM` to proceed."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            await interaction.response.defer()

            # Get all current members (excluding bots)
            current_members = [member for member in interaction.guild.members if not member.bot]

            processed_count = 0
            already_processed = 0
            errors = 0

            async with self.bot.database.pool.acquire() as conn:
                for member in current_members:
                    try:
                        # Check if they already have quest progress
                        existing_progress = await conn.fetchrow('''
                            SELECT status FROM quest_progress 
                            WHERE user_id = $1 AND guild_id = $2 
                            AND quest_id LIKE 'starter%'
                            LIMIT 1
                        ''', member.id, interaction.guild.id)

                        if existing_progress:
                            already_processed += 1
                            continue

                        # Check if they have welcome automation record
                        welcome_record = await conn.fetchrow('''
                            SELECT starter_quest_1, mentor_id FROM welcome_automation
                            WHERE user_id = $1 AND guild_id = $2
                        ''', member.id, interaction.guild.id)

                        # Determine which starter quest to use
                        starter_quest_id = 'starter5'  # Default fallback
                        if welcome_record and welcome_record['starter_quest_1']:
                            starter_quest_id = welcome_record['starter_quest_1']

                        # Skip if they have a mentor (mentored students don't need starter quests)
                        if welcome_record and welcome_record['mentor_id']:
                            already_processed += 1
                            continue

                        # Create quest progress as "completed" (submitted for approval)
                        await conn.execute('''
                            INSERT INTO quest_progress (quest_id, user_id, guild_id, status, 
                                                      accepted_at, completed_at, proof_text, 
                                                      proof_image_urls, channel_id)
                            VALUES ($1, $2, $3, 'completed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 
                                   'Bulk submitted by admin for existing members', ARRAY[]::TEXT[], 0)
                            ON CONFLICT (quest_id, user_id) DO NOTHING
                        ''', starter_quest_id, member.id, interaction.guild.id)

                        # Update welcome automation record
                        if welcome_record:
                            await conn.execute('''
                                UPDATE welcome_automation 
                                SET quest_1_completed = TRUE, last_activity = CURRENT_TIMESTAMP
                                WHERE user_id = $1 AND guild_id = $2
                            ''', member.id, interaction.guild.id)
                        else:
                            # Create welcome record for members who don't have one
                            await conn.execute('''
                                INSERT INTO welcome_automation (user_id, guild_id, starter_quest_1, 
                                                              quest_1_completed, welcome_sent, 
                                                              new_disciple_role_awarded)
                                VALUES ($1, $2, $3, TRUE, TRUE, FALSE)
                                ON CONFLICT (user_id, guild_id) DO UPDATE SET
                                    starter_quest_1 = EXCLUDED.starter_quest_1,
                                    quest_1_completed = TRUE
                            ''', member.id, interaction.guild.id, starter_quest_id)

                        processed_count += 1

                    except Exception as member_error:
                        logger.error(f"❌ Error processing member {member.display_name}: {member_error}")
                        errors += 1

            # Send results
            from bot.utils import create_success_embed
            embed = create_success_embed(
                "Bulk Starter Quest Submission Complete!",
                f"Successfully processed starter quest submissions for current server members."
            )

            embed.add_field(
                name="━━━━━━━━━ Processing Results ━━━━━━━━━",
                value=(
                    f"**✅ Processed:** {processed_count} members\n"
                    f"**⏭️ Already Processed:** {already_processed} members\n"
                    f"**❌ Errors:** {errors} members\n"
                    f"**📊 Total Members:** {len(current_members)} (excluding bots)\n\n"
                    f"**All processed members now appear in pending approval queue.**"
                ),
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Next Steps ━━━━━━━━━",
                value=(
                    f"**1.** Use `/pendingapproval` to see all submissions\n"
                    f"**2.** Use `/approve quest_id user approved:True/False` to approve/reject each one\n"
                    f"**3.** Approved members will automatically receive the Demon Apprentice role\n"
                    f"**4.** This was a one-time bulk operation for existing members only\n\n"
                    f"**New members joining will still go through normal welcome flow.**"
                ),
                inline=False
            )

            await interaction.followup.send(embed=embed)

            logger.info(f"✅ Admin {interaction.user.display_name} completed bulk starter submission: {processed_count} processed, {already_processed} skipped, {errors} errors")

        except Exception as e:
            logger.error(f"❌ Error in bulk_submit_starters: {e}")
            from bot.utils import create_error_embed
            embed = create_error_embed(
                "Bulk Submission Failed",
                "An error occurred during the bulk submission process.",
                str(e)
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    """Setup function for the cog"""
    await bot.add_cog(AdminPerformanceCommands(bot))