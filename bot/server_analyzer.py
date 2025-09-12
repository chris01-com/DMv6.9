import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ServerAnalyzer(commands.Cog):
    """Analyze Discord server structure and provide insights"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="analyze_server", description="Analyze server structure and channels (Admin only)")
    async def analyze_server(self, interaction: discord.Interaction):
        """Analyze the current server structure"""
        try:
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ This command requires administrator permissions.", ephemeral=True)
                return
            
            await interaction.response.defer()
            
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("❌ This command must be used in a server.", ephemeral=True)
                return
            
            # Analyze server structure
            analysis = await self._analyze_guild(guild)
            
            # Create comprehensive embed
            embed = discord.Embed(
                title=f"📊 Server Analysis: {guild.name}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            # Basic server info
            embed.add_field(
                name="🏰 Server Overview",
                value=(
                    f"**Name:** {guild.name}\n"
                    f"**ID:** {guild.id}\n"
                    f"**Owner:** {guild.owner.mention if guild.owner else 'Unknown'}\n"
                    f"**Created:** {guild.created_at.strftime('%Y-%m-%d')}\n"
                    f"**Members:** {guild.member_count:,}\n"
                    f"**Verification:** {guild.verification_level.name.title()}"
                ),
                inline=True
            )
            
            # Channel breakdown
            embed.add_field(
                name="📋 Channels",
                value=(
                    f"**Total:** {len(guild.channels)}\n"
                    f"**Text:** {len(analysis['text_channels'])}\n"
                    f"**Voice:** {len(analysis['voice_channels'])}\n"
                    f"**Categories:** {len(analysis['categories'])}\n"
                    f"**Threads:** {len(analysis['threads'])}"
                ),
                inline=True
            )
            
            # Role breakdown
            embed.add_field(
                name="👥 Roles",
                value=(
                    f"**Total:** {len(guild.roles)}\n"
                    f"**Hoisted:** {len([r for r in guild.roles if r.hoist])}\n"
                    f"**Mentionable:** {len([r for r in guild.roles if r.mentionable])}\n"
                    f"**Managed:** {len([r for r in guild.roles if r.managed])}"
                ),
                inline=True
            )
            
            # Channel details by category
            if analysis['channel_structure']:
                channel_details = ""
                for category, channels in analysis['channel_structure'].items():
                    if len(channel_details) > 800:  # Prevent embed from being too long
                        channel_details += "\n*...and more*"
                        break
                    channel_details += f"**{category}:**\n"
                    for channel in channels[:5]:  # Limit to 5 channels per category
                        channel_details += f"  • {channel['name']} ({channel['type']})\n"
                    if len(channels) > 5:
                        channel_details += f"  • *...and {len(channels) - 5} more*\n"
                    channel_details += "\n"
                
                embed.add_field(
                    name="🗂️ Channel Structure",
                    value=channel_details[:1024] if channel_details else "No organized structure found",
                    inline=False
                )
            
            # Top roles
            if analysis['top_roles']:
                role_list = ""
                for role in analysis['top_roles'][:10]:
                    if len(role_list) > 200:
                        role_list += "\n*...and more*"
                        break
                    role_list += f"• {role['name']} ({role['members']} members)\n"
                
                embed.add_field(
                    name="🎭 Top Roles",
                    value=role_list[:1024] if role_list else "No roles found",
                    inline=True
                )
            
            # Bot recommendations
            recommendations = self._generate_recommendations(analysis)
            if recommendations:
                embed.add_field(
                    name="💡 Growth Recommendations",
                    value=recommendations[:1024],
                    inline=False
                )
            
            embed.set_footer(text=f"Analysis for {guild.name}")
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"❌ Error in server analysis: {e}")
            embed = discord.Embed(
                title="Error",
                description="Failed to analyze server structure.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
    
    async def _analyze_guild(self, guild: discord.Guild) -> Dict[str, Any]:
        """Perform detailed guild analysis"""
        analysis = {
            'text_channels': [],
            'voice_channels': [],
            'categories': [],
            'threads': [],
            'channel_structure': {},
            'top_roles': [],
            'member_stats': {},
            'activity_patterns': {}
        }
        
        # Analyze channels
        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel):
                analysis['text_channels'].append({
                    'id': channel.id,
                    'name': channel.name,
                    'category': channel.category.name if channel.category else 'Uncategorized',
                    'permissions': len(channel.overwrites),
                    'position': channel.position
                })
            elif isinstance(channel, discord.VoiceChannel):
                analysis['voice_channels'].append({
                    'id': channel.id,
                    'name': channel.name,
                    'category': channel.category.name if channel.category else 'Uncategorized',
                    'user_limit': channel.user_limit
                })
            elif isinstance(channel, discord.CategoryChannel):
                analysis['categories'].append({
                    'id': channel.id,
                    'name': channel.name,
                    'channels': len(channel.channels)
                })
        
        # Organize channels by category
        for channel_data in analysis['text_channels'] + analysis['voice_channels']:
            category = channel_data['category']
            if category not in analysis['channel_structure']:
                analysis['channel_structure'][category] = []
            
            channel_type = 'text' if channel_data in analysis['text_channels'] else 'voice'
            analysis['channel_structure'][category].append({
                'name': channel_data['name'],
                'type': channel_type,
                'id': channel_data['id']
            })
        
        # Analyze roles
        for role in guild.roles:
            if role.name != "@everyone" and not role.managed:
                analysis['top_roles'].append({
                    'id': role.id,
                    'name': role.name,
                    'members': len(role.members),
                    'color': str(role.color),
                    'permissions': role.permissions.value,
                    'position': role.position
                })
        
        # Sort roles by member count
        analysis['top_roles'].sort(key=lambda x: x['members'], reverse=True)
        
        return analysis
    
    def _generate_recommendations(self, analysis: Dict[str, Any]) -> str:
        """Generate growth recommendations based on analysis"""
        recommendations = []
        
        # Channel organization recommendations
        if len(analysis['text_channels']) > 15:
            recommendations.append("• Consider using more categories to organize channels")
        
        if 'Uncategorized' in analysis['channel_structure'] and len(analysis['channel_structure']['Uncategorized']) > 3:
            recommendations.append("• Move uncategorized channels into proper categories")
        
        # Role structure recommendations
        if len(analysis['top_roles']) < 5:
            recommendations.append("• Add more role variety for better member engagement")
        
        # Quest system recommendations
        quest_channels = [ch for ch in analysis['text_channels'] if 'quest' in ch['name'].lower()]
        if len(quest_channels) < 3:
            recommendations.append("• Create dedicated quest channels (list, submit, approval)")
        
        # Community engagement recommendations
        social_channels = [ch for ch in analysis['text_channels'] if any(word in ch['name'].lower() for word in ['chat', 'general', 'talk', 'social'])]
        if len(social_channels) < 2:
            recommendations.append("• Add more social channels for community building")
        
        if not recommendations:
            recommendations.append("• Server structure looks well organized!")
        
        return "\n".join(recommendations[:5])  # Limit to 5 recommendations

async def setup(bot):
    await bot.add_cog(ServerAnalyzer(bot))