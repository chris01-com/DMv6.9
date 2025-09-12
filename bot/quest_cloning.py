import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import uuid
import discord
from bot.models import Quest, QuestRank, QuestCategory, QuestStatus

logger = logging.getLogger(__name__)

class QuestCloningSystem:
    """System for duplicating and modifying successful quests"""
    
    def __init__(self, database, quest_manager):
        self.database = database
        self.quest_manager = quest_manager
    
    async def initialize_cloning_system(self):
        """Initialize quest cloning system"""
        try:
            async with self.database.pool.acquire() as conn:
                # Quest clones table to track relationships
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_clones (
                        clone_id VARCHAR(50) PRIMARY KEY,
                        original_id VARCHAR(50) NOT NULL,
                        cloned_by BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        clone_reason TEXT,
                        cloned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        modifications TEXT -- JSON of what was changed
                    )
                ''')
                
                # Quest templates table for reusable quest structures
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_templates (
                        template_id VARCHAR(50) PRIMARY KEY,
                        guild_id BIGINT NOT NULL,
                        creator_id BIGINT NOT NULL,
                        template_name VARCHAR(255) NOT NULL,
                        description TEXT,
                        category VARCHAR(100) NOT NULL,
                        rank VARCHAR(50) NOT NULL,
                        requirements_template TEXT,
                        reward_template TEXT,
                        title_template VARCHAR(255),
                        description_template TEXT,
                        is_public BOOLEAN DEFAULT FALSE,
                        usage_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
            logger.info("✅ Quest cloning system initialized")
            
        except Exception as e:
            logger.error(f"❌ Error initializing quest cloning: {e}")
    
    async def clone_quest(self, original_id: str, cloner_id: int, guild_id: int, 
                         modifications: Optional[Dict] = None, clone_reason: str = "") -> Tuple[Optional[Quest], str]:
        """
        Clone an existing quest with optional modifications
        
        Parameters:
        - original_id: Quest to clone
        - cloner_id: User cloning the quest
        - guild_id: Target guild
        - modifications: Dict of fields to change in the clone
        - clone_reason: Why the quest is being cloned
        
        Returns: (cloned_quest, message)
        """
        try:
            # Get original quest
            original_quest = await self.quest_manager.get_quest(original_id)
            if not original_quest:
                return None, "Original quest not found"
            
            # Generate new quest ID
            new_quest_id = str(uuid.uuid4())[:8]
            
            # Start with original quest data
            clone_data = {
                'quest_id': new_quest_id,
                'title': original_quest.title,
                'description': original_quest.description,
                'creator_id': cloner_id,
                'guild_id': guild_id,
                'requirements': original_quest.requirements,
                'reward': original_quest.reward,
                'rank': original_quest.rank,
                'category': original_quest.category,
                'status': QuestStatus.AVAILABLE,
                'created_at': datetime.now(),
                'required_role_ids': original_quest.required_role_ids.copy() if original_quest.required_role_ids else []
            }
            
            # Apply modifications if provided
            modification_log = {}
            if modifications:
                for field, new_value in modifications.items():
                    if field in clone_data and field != 'quest_id':  # Don't allow changing quest ID
                        old_value = clone_data[field]
                        clone_data[field] = new_value
                        modification_log[field] = {'old': old_value, 'new': new_value}
            
            # Create the cloned quest
            cloned_quest = Quest(**clone_data)
            
            # Save cloned quest
            await self.database.save_quest(cloned_quest)
            
            # Record cloning relationship
            await self._record_clone_relationship(
                new_quest_id, original_id, cloner_id, guild_id, 
                clone_reason, modification_log
            )
            
            logger.info(f"✅ Quest {original_id} cloned as {new_quest_id} by {cloner_id}")
            return cloned_quest, f"Quest cloned successfully! New ID: {new_quest_id}"
            
        except Exception as e:
            logger.error(f"❌ Error cloning quest: {e}")
            return None, f"Cloning failed: {str(e)}"
    
    async def create_seasonal_variant(self, original_id: str, cloner_id: int, guild_id: int,
                                    season_theme: str, season_modifications: Optional[Dict] = None) -> Tuple[Optional[Quest], str]:
        """Create a seasonal variant of a quest"""
        
        # Predefined seasonal modifications
        seasonal_themes = {
            'winter': {
                'title_suffix': ' (Winter Edition)',
                'description_additions': '\n\n❄️ *Special winter themed quest*',
                'reward_bonus': ' + Winter Badge'
            },
            'summer': {
                'title_suffix': ' (Summer Festival)',
                'description_additions': '\n\n☀️ *Summer festival special quest*',
                'reward_bonus': ' + Summer Badge'
            },
            'halloween': {
                'title_suffix': ' (Halloween Special)',
                'description_additions': '\n\n🎃 *Spooky Halloween themed quest*',
                'reward_bonus': ' + Spooky Badge'
            },
            'holiday': {
                'title_suffix': ' (Holiday Special)',
                'description_additions': '\n\n🎄 *Holiday season themed quest*',
                'reward_bonus': ' + Holiday Badge'
            }
        }
        
        if season_theme.lower() not in seasonal_themes:
            return None, f"Unknown seasonal theme: {season_theme}"
        
        original_quest = await self.quest_manager.get_quest(original_id)
        if not original_quest:
            return None, "Original quest not found"
        
        theme_data = seasonal_themes[season_theme.lower()]
        
        # Apply seasonal modifications
        modifications = season_modifications or {}
        modifications.update({
            'title': original_quest.title + theme_data['title_suffix'],
            'description': original_quest.description + theme_data['description_additions'],
            'reward': original_quest.reward + theme_data['reward_bonus']
        })
        
        clone_reason = f"Seasonal variant for {season_theme} theme"
        
        return await self.clone_quest(original_id, cloner_id, guild_id, modifications, clone_reason)
    
    async def create_difficulty_variant(self, original_id: str, cloner_id: int, guild_id: int,
                                      new_rank: str, scaling_factor: float = 1.5) -> Tuple[Optional[Quest], str]:
        """Create a quest variant with different difficulty"""
        
        original_quest = await self.quest_manager.get_quest(original_id)
        if not original_quest:
            return None, "Original quest not found"
        
        # Validate new rank
        valid_ranks = [QuestRank.EASY, QuestRank.NORMAL, QuestRank.MEDIUM, QuestRank.HARD, QuestRank.IMPOSSIBLE]
        if new_rank not in valid_ranks:
            return None, f"Invalid rank: {new_rank}"
        
        # Calculate scaled reward
        original_points = self._extract_points_from_reward(original_quest.reward)
        if original_points:
            new_points = int(original_points * scaling_factor)
            new_reward = original_quest.reward.replace(str(original_points), str(new_points))
        else:
            new_reward = original_quest.reward
        
        # Modify title and requirements based on difficulty
        rank_modifiers = {
            QuestRank.EASY: {'title': ' (Easy)', 'req_note': '\n• Beginner friendly version'},
            QuestRank.NORMAL: {'title': ' (Standard)', 'req_note': '\n• Standard difficulty'},
            QuestRank.MEDIUM: {'title': ' (Challenging)', 'req_note': '\n• Increased difficulty'},
            QuestRank.HARD: {'title': ' (Expert)', 'req_note': '\n• Expert level challenge'},
            QuestRank.IMPOSSIBLE: {'title': ' (Legendary)', 'req_note': '\n• Legendary difficulty - extreme challenge!'}
        }
        
        modifier = rank_modifiers.get(new_rank, {'title': '', 'req_note': ''})
        
        modifications = {
            'title': original_quest.title + modifier['title'],
            'rank': new_rank,
            'reward': new_reward,
            'requirements': original_quest.requirements + modifier['req_note']
        }
        
        clone_reason = f"Difficulty variant ({new_rank} version)"
        
        return await self.clone_quest(original_id, cloner_id, guild_id, modifications, clone_reason)
    
    async def get_successful_quests_for_cloning(self, guild_id: int, min_completions: int = 3) -> List[Dict]:
        """Get quests that are good candidates for cloning based on completion rates"""
        try:
            async with self.database.pool.acquire() as conn:
                successful_quests = await conn.fetch('''
                    SELECT q.*, 
                           COUNT(qp.quest_id) as total_attempts,
                           COUNT(CASE WHEN qp.status = 'approved' THEN 1 END) as completions,
                           ROUND(
                               COUNT(CASE WHEN qp.status = 'approved' THEN 1 END)::float / 
                               NULLIF(COUNT(qp.quest_id), 0) * 100, 2
                           ) as success_rate
                    FROM quests q
                    LEFT JOIN quest_progress qp ON q.quest_id = qp.quest_id
                    WHERE q.guild_id = $1
                    GROUP BY q.quest_id, q.title, q.description, q.creator_id, q.guild_id,
                             q.requirements, q.reward, q.rank, q.category, q.status,
                             q.created_at, q.required_role_ids
                    HAVING COUNT(CASE WHEN qp.status = 'approved' THEN 1 END) >= $2
                    ORDER BY success_rate DESC, completions DESC
                    LIMIT 20
                ''', guild_id, min_completions)
                
                return [dict(row) for row in successful_quests]
                
        except Exception as e:
            logger.error(f"❌ Error getting successful quests: {e}")
            return []
    
    async def get_clone_history(self, original_id: str) -> List[Dict]:
        """Get all clones of a specific quest"""
        try:
            async with self.database.pool.acquire() as conn:
                clones = await conn.fetch('''
                    SELECT qc.*, q.title, q.status, q.creator_id as clone_creator
                    FROM quest_clones qc
                    JOIN quests q ON qc.clone_id = q.quest_id
                    WHERE qc.original_id = $1
                    ORDER BY qc.cloned_at DESC
                ''', original_id)
                
                return [dict(row) for row in clones]
                
        except Exception as e:
            logger.error(f"❌ Error getting clone history: {e}")
            return []
    
    async def save_as_template(self, quest_id: str, creator_id: int, template_name: str,
                              description: str = "", is_public: bool = False) -> Tuple[bool, str]:
        """Save a quest as a reusable template"""
        try:
            quest = await self.quest_manager.get_quest(quest_id)
            if not quest:
                return False, "Quest not found"
            
            template_id = str(uuid.uuid4())[:8]
            
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO quest_templates 
                    (template_id, guild_id, creator_id, template_name, description, category, rank,
                     requirements_template, reward_template, title_template, description_template, is_public)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ''', template_id, quest.guild_id, creator_id, template_name, description,
                quest.category, quest.rank, quest.requirements, quest.reward,
                quest.title, quest.description, is_public)
                
            logger.info(f"✅ Quest {quest_id} saved as template '{template_name}' by {creator_id}")
            return True, f"Template '{template_name}' created successfully! ID: {template_id}"
            
        except Exception as e:
            logger.error(f"❌ Error saving quest template: {e}")
            return False, f"Failed to save template: {str(e)}"
    
    async def create_quest_from_template(self, template_id: str, creator_id: int, guild_id: int,
                                       customizations: Optional[Dict] = None) -> Tuple[Optional[Quest], str]:
        """Create a new quest from a template"""
        try:
            # Get template
            async with self.database.pool.acquire() as conn:
                template = await conn.fetchrow('''
                    SELECT * FROM quest_templates WHERE template_id = $1
                ''', template_id)
                
                if not template:
                    return None, "Template not found"
                
                # Increment usage count
                await conn.execute('''
                    UPDATE quest_templates SET usage_count = usage_count + 1
                    WHERE template_id = $1
                ''', template_id)
            
            # Create quest from template
            new_quest_id = str(uuid.uuid4())[:8]
            
            quest_data = {
                'quest_id': new_quest_id,
                'title': template['title_template'],
                'description': template['description_template'],
                'creator_id': creator_id,
                'guild_id': guild_id,
                'requirements': template['requirements_template'],
                'reward': template['reward_template'],
                'rank': template['rank'],
                'category': template['category'],
                'status': QuestStatus.AVAILABLE,
                'created_at': datetime.now(),
                'required_role_ids': []
            }
            
            # Apply customizations
            if customizations:
                for field, value in customizations.items():
                    if field in quest_data and field != 'quest_id':
                        quest_data[field] = value
            
            # Create quest
            quest = Quest(**quest_data)
            await self.database.save_quest(quest)
            
            logger.info(f"✅ Quest created from template {template_id} by {creator_id}")
            return quest, f"Quest created from template! New ID: {new_quest_id}"
            
        except Exception as e:
            logger.error(f"❌ Error creating quest from template: {e}")
            return None, f"Template creation failed: {str(e)}"
    
    async def get_available_templates(self, guild_id: int, user_id: Optional[int] = None) -> List[Dict]:
        """Get available quest templates"""
        try:
            async with self.database.pool.acquire() as conn:
                if user_id:
                    # Get public templates and user's private templates
                    templates = await conn.fetch('''
                        SELECT * FROM quest_templates 
                        WHERE (guild_id = $1 AND is_public = TRUE) 
                           OR (guild_id = $1 AND creator_id = $2)
                        ORDER BY usage_count DESC, created_at DESC
                    ''', guild_id, user_id)
                else:
                    # Get only public templates
                    templates = await conn.fetch('''
                        SELECT * FROM quest_templates 
                        WHERE guild_id = $1 AND is_public = TRUE
                        ORDER BY usage_count DESC, created_at DESC
                    ''', guild_id)
                
                return [dict(row) for row in templates]
                
        except Exception as e:
            logger.error(f"❌ Error getting templates: {e}")
            return []
    
    def _extract_points_from_reward(self, reward_text: str) -> Optional[int]:
        """Extract numeric points from reward text"""
        if not reward_text:
            return None
            
        import re
        # Look for patterns like "50 points", "100pts", etc.
        patterns = [r'(\d+)\s*points?', r'(\d+)\s*pts?', r'(\d+)']
        
        for pattern in patterns:
            match = re.search(pattern, reward_text.lower())
            if match:
                return int(match.group(1))
                
        return None
    
    async def _record_clone_relationship(self, clone_id: str, original_id: str, cloner_id: int,
                                       guild_id: int, reason: str, modifications: Dict):
        """Record the clone relationship in database"""
        try:
            import json
            modifications_json = json.dumps(modifications)
            
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO quest_clones 
                    (clone_id, original_id, cloned_by, guild_id, clone_reason, modifications)
                    VALUES ($1, $2, $3, $4, $5, $6)
                ''', clone_id, original_id, cloner_id, guild_id, reason, modifications_json)
                
        except Exception as e:
            logger.error(f"❌ Error recording clone relationship: {e}")
    
    def create_cloning_candidates_embed(self, successful_quests: List[Dict]) -> discord.Embed:
        """Create embed showing good quests for cloning"""
        if not successful_quests:
            embed = discord.Embed(
                title="📄 Quest Cloning Candidates",
                description="No quests with sufficient completion data found.",
                color=discord.Color.orange()
            )
            return embed
        
        embed = discord.Embed(
            title="📄 Quest Cloning Candidates",
            description=f"Top {len(successful_quests)} quests based on success rate and completions:",
            color=discord.Color.green()
        )
        
        for i, quest in enumerate(successful_quests[:10], 1):  # Limit to 10
            success_rate = quest['success_rate'] or 0
            rank_emoji = self._get_rank_emoji(quest['rank'])
            
            embed.add_field(
                name=f"{i}. {rank_emoji} {quest['title']} ({quest['quest_id']})",
                value=(f"**Success Rate:** {success_rate}% ({quest['completions']}/{quest['total_attempts']})\n"
                      f"**Category:** {quest['category'].title()}\n"
                      f"**Creator:** <@{quest['creator_id']}>\n"
                      f"*Use `/clone_quest {quest['quest_id']}` to clone*"),
                inline=False
            )
        
        embed.set_footer(text="High success rate quests make great templates for cloning")
        return embed
    
    def create_templates_embed(self, templates: List[Dict]) -> discord.Embed:
        """Create embed showing available quest templates"""
        if not templates:
            embed = discord.Embed(
                title="📋 Quest Templates",
                description="No quest templates available.",
                color=discord.Color.light_grey()
            )
            return embed
        
        embed = discord.Embed(
            title="📋 Available Quest Templates",
            description=f"Choose from {len(templates)} proven quest templates:",
            color=discord.Color.blue()
        )
        
        for template in templates[:10]:  # Limit to 10
            visibility = "🌍 Public" if template['is_public'] else "🔒 Private"
            rank_emoji = self._get_rank_emoji(template['rank'])
            
            embed.add_field(
                name=f"{rank_emoji} {template['template_name']} ({template['template_id']})",
                value=(f"**Category:** {template['category'].title()} • **Rank:** {template['rank'].title()}\n"
                      f"**Usage:** {template['usage_count']} times • {visibility}\n"
                      f"{template['description'][:80] if template['description'] else 'No description'}{'...' if template['description'] and len(template['description']) > 80 else ''}\n"
                      f"*Creator: <@{template['creator_id']}>*"),
                inline=False
            )
        
        embed.set_footer(text="Use /create_from_template <template_id> to create a quest")
        return embed
    
    def _get_rank_emoji(self, rank: str) -> str:
        """Get emoji for quest rank"""
        emojis = {
            QuestRank.EASY: "🟢",
            QuestRank.NORMAL: "🔵",
            QuestRank.MEDIUM: "🟠",
            QuestRank.HARD: "🔴",
            QuestRank.IMPOSSIBLE: "🟣"
        }
        return emojis.get(rank, "⚪")