import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import discord
from bot.models import Quest, QuestRank, QuestCategory, QuestStatus

logger = logging.getLogger(__name__)

class QuestRecommendationSystem:
    """Smart quest recommendation system based on user history and preferences"""
    
    def __init__(self, database, quest_manager):
        self.database = database
        self.quest_manager = quest_manager
        
        # Rank progression mapping
        self.rank_progression = {
            QuestRank.EASY: QuestRank.NORMAL,
            QuestRank.NORMAL: QuestRank.MEDIUM,
            QuestRank.MEDIUM: QuestRank.HARD,
            QuestRank.HARD: QuestRank.IMPOSSIBLE
        }
    
    async def get_personalized_recommendations(self, user_id: int, guild_id: int, limit: int = 10) -> List[Tuple[Quest, str, float]]:
        """
        Get personalized quest recommendations for a user
        Returns: List of (Quest, reason, confidence_score)
        """
        try:
            # Get user's quest history and preferences
            user_profile = await self._build_user_profile(user_id, guild_id)
            
            # Get available quests
            available_quests = await self.quest_manager.get_available_quests(guild_id)
            
            # Filter out quests user has already accepted/completed
            eligible_quests = await self._filter_eligible_quests(available_quests, user_id)
            
            # Score and rank quests
            recommendations = []
            for quest in eligible_quests:
                score, reason = await self._calculate_recommendation_score(quest, user_profile, user_id, guild_id)
                if score > 0.1:  # Only recommend quests with decent scores
                    recommendations.append((quest, reason, score))
            
            # Sort by score (highest first) and return top results
            recommendations.sort(key=lambda x: x[2], reverse=True)
            return recommendations[:limit]
            
        except Exception as e:
            logger.error(f"❌ Error generating recommendations: {e}")
            return []
    
    async def get_skill_progression_recommendations(self, user_id: int, guild_id: int, limit: int = 5) -> List[Tuple[Quest, str]]:
        """Get quests that help user progress in difficulty"""
        try:
            # Get user's highest completed rank in each category
            async with self.database.pool.acquire() as conn:
                user_progress = await conn.fetch('''
                    SELECT q.category, q.rank, COUNT(*) as completed_count
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id
                    WHERE qp.user_id = $1 AND qp.guild_id = $2 AND qp.status = 'approved'
                    GROUP BY q.category, q.rank
                    ORDER BY q.category, 
                        CASE q.rank 
                            WHEN 'easy' THEN 1 
                            WHEN 'normal' THEN 2 
                            WHEN 'medium' THEN 3 
                            WHEN 'hard' THEN 4 
                            WHEN 'impossible' THEN 5 
                        END
                ''', user_id, guild_id)
            
            # Find next level quests for each category
            category_progress = {}
            for row in user_progress:
                category = row['category']
                rank = row['rank']
                if category not in category_progress:
                    category_progress[category] = []
                category_progress[category].append(rank)
            
            recommendations = []
            available_quests = await self.quest_manager.get_available_quests(guild_id)
            
            for quest in available_quests:
                if quest.category in category_progress:
                    user_ranks = category_progress[quest.category]
                    # Find the highest rank user completed in this category
                    highest_completed = self._get_highest_rank(user_ranks)
                    suggested_next = self.rank_progression.get(highest_completed)
                    
                    if quest.rank == suggested_next:
                        reason = f"Next level in {quest.category} - you've mastered {highest_completed.title()}"
                        recommendations.append((quest, reason))
                        
                elif quest.rank == QuestRank.EASY:
                    # User hasn't done any quests in this category
                    reason = f"New category: Start with {quest.category.title()} quests"
                    recommendations.append((quest, reason))
            
            return recommendations[:limit]
            
        except Exception as e:
            logger.error(f"❌ Error getting skill progression recommendations: {e}")
            return []
    
    async def get_similar_user_recommendations(self, user_id: int, guild_id: int, limit: int = 5) -> List[Tuple[Quest, str]]:
        """Find quests that similar users have completed"""
        try:
            # Find users with similar quest completion patterns
            async with self.database.pool.acquire() as conn:
                # Get categories user has completed
                user_categories = await conn.fetch('''
                    SELECT DISTINCT q.category
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id
                    WHERE qp.user_id = $1 AND qp.guild_id = $2 AND qp.status = 'approved'
                ''', user_id, guild_id)
                
                if not user_categories:
                    return []
                
                user_cat_list = [row['category'] for row in user_categories]
                
                # Find users who completed similar categories
                similar_users = await conn.fetch('''
                    SELECT qp.user_id, COUNT(DISTINCT q.category) as common_categories
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id
                    WHERE qp.guild_id = $1 AND qp.status = 'approved'
                    AND q.category = ANY($2) AND qp.user_id != $3
                    GROUP BY qp.user_id
                    HAVING COUNT(DISTINCT q.category) >= $4
                    ORDER BY common_categories DESC
                    LIMIT 10
                ''', guild_id, user_cat_list, user_id, max(1, len(user_cat_list) // 2))
                
                if not similar_users:
                    return []
                
                similar_user_ids = [row['user_id'] for row in similar_users]
                
                # Get quests completed by similar users that current user hasn't done
                recommended_quests = await conn.fetch('''
                    SELECT q.*, COUNT(*) as completion_count
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id
                    WHERE qp.user_id = ANY($1) AND qp.guild_id = $2 AND qp.status = 'approved'
                    AND q.quest_id NOT IN (
                        SELECT quest_id FROM quest_progress 
                        WHERE user_id = $3 AND (status = 'accepted' OR status = 'completed' OR status = 'approved')
                    )
                    AND q.status = 'available'
                    GROUP BY q.quest_id, q.title, q.description, q.creator_id, q.guild_id, 
                             q.requirements, q.reward, q.rank, q.category, q.status, 
                             q.created_at, q.required_role_ids
                    ORDER BY completion_count DESC
                    LIMIT $4
                ''', similar_user_ids, guild_id, user_id, limit)
                
                recommendations = []
                for row in recommended_quests:
                    quest = Quest(
                        quest_id=row['quest_id'],
                        title=row['title'],
                        description=row['description'],
                        creator_id=row['creator_id'],
                        guild_id=row['guild_id'],
                        requirements=row['requirements'] or "",
                        reward=row['reward'] or "",
                        rank=row['rank'] or QuestRank.NORMAL,
                        category=row['category'] or QuestCategory.OTHER,
                        status=row['status'] or QuestStatus.AVAILABLE,
                        created_at=row['created_at'],
                        required_role_ids=row.get('required_role_ids', []) or []
                    )
                    
                    count = row['completion_count']
                    reason = f"Popular with similar users ({count} completions)"
                    recommendations.append((quest, reason))
                
                return recommendations
                
        except Exception as e:
            logger.error(f"❌ Error getting similar user recommendations: {e}")
            return []
    
    async def _build_user_profile(self, user_id: int, guild_id: int) -> Dict:
        """Build user profile for recommendations"""
        try:
            async with self.database.pool.acquire() as conn:
                # Get completion statistics
                stats = await conn.fetchrow('''
                    SELECT 
                        COUNT(*) as total_completed,
                        AVG(CASE WHEN qp.completed_at IS NOT NULL AND qp.accepted_at IS NOT NULL 
                            THEN EXTRACT(EPOCH FROM (qp.completed_at - qp.accepted_at))/3600 
                            ELSE NULL END) as avg_completion_hours
                    FROM quest_progress qp
                    WHERE qp.user_id = $1 AND qp.guild_id = $2 AND qp.status = 'approved'
                ''', user_id, guild_id)
                
                # Get category preferences (completion counts)
                categories = await conn.fetch('''
                    SELECT q.category, COUNT(*) as completed_count
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id
                    WHERE qp.user_id = $1 AND qp.guild_id = $2 AND qp.status = 'approved'
                    GROUP BY q.category
                    ORDER BY completed_count DESC
                ''', user_id, guild_id)
                
                # Get rank preferences
                ranks = await conn.fetch('''
                    SELECT q.rank, COUNT(*) as completed_count
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id
                    WHERE qp.user_id = $1 AND qp.guild_id = $2 AND qp.status = 'approved'
                    GROUP BY q.rank
                    ORDER BY completed_count DESC
                ''', user_id, guild_id)
                
                # Get recent activity
                recent_activity = await conn.fetchval('''
                    SELECT COUNT(*)
                    FROM quest_progress qp
                    WHERE qp.user_id = $1 AND qp.guild_id = $2 
                    AND qp.accepted_at >= $3
                ''', user_id, guild_id, datetime.now() - timedelta(days=30))
                
                profile = {
                    'total_completed': stats['total_completed'] or 0,
                    'avg_completion_hours': float(stats['avg_completion_hours'] or 24),
                    'category_preferences': {row['category']: row['completed_count'] for row in categories},
                    'rank_preferences': {row['rank']: row['completed_count'] for row in ranks},
                    'recent_activity': recent_activity or 0,
                    'favorite_categories': [row['category'] for row in categories[:3]],
                    'comfort_ranks': [row['rank'] for row in ranks[:2]]
                }
                
                return profile
                
        except Exception as e:
            logger.error(f"❌ Error building user profile: {e}")
            return {}
    
    async def _filter_eligible_quests(self, quests: List[Quest], user_id: int) -> List[Quest]:
        """Filter out quests user already has or completed"""
        try:
            async with self.database.pool.acquire() as conn:
                user_quests = await conn.fetch('''
                    SELECT quest_id FROM quest_progress 
                    WHERE user_id = $1 AND status IN ('accepted', 'completed', 'approved')
                ''', user_id)
                
                user_quest_ids = {row['quest_id'] for row in user_quests}
                
                return [quest for quest in quests if quest.quest_id not in user_quest_ids]
                
        except Exception as e:
            logger.error(f"❌ Error filtering eligible quests: {e}")
            return quests
    
    async def _calculate_recommendation_score(self, quest: Quest, user_profile: Dict, user_id: int, guild_id: int) -> Tuple[float, str]:
        """Calculate recommendation score and reason for a quest"""
        score = 0.0
        reasons = []
        
        if not user_profile:
            return 0.1, "New quest available"
        
        # Category preference bonus
        if quest.category in user_profile.get('favorite_categories', []):
            category_bonus = 0.4
            score += category_bonus
            reasons.append(f"matches your favorite category ({quest.category.title()})")
        
        # Rank comfort bonus
        if quest.rank in user_profile.get('comfort_ranks', []):
            rank_bonus = 0.3
            score += rank_bonus
            reasons.append(f"comfortable difficulty ({quest.rank.title()})")
        
        # Skill progression bonus
        if quest.category in user_profile.get('category_preferences', {}):
            # User has done this category before
            cat_count = user_profile['category_preferences'][quest.category]
            if cat_count >= 3 and quest.rank in [QuestRank.MEDIUM, QuestRank.HARD]:
                score += 0.3
                reasons.append("good progression challenge")
        
        # New category encouragement
        if quest.category not in user_profile.get('category_preferences', {}) and quest.rank == QuestRank.EASY:
            score += 0.2
            reasons.append("explore new category")
        
        # Recent activity bonus (active users get more recommendations)
        if user_profile.get('recent_activity', 0) > 2:
            score += 0.1
            reasons.append("you've been active recently")
        
        # Base score for any available quest
        score += 0.1
        
        # Combine reasons
        if not reasons:
            reason = "Available quest"
        elif len(reasons) == 1:
            reason = f"Recommended: {reasons[0]}"
        else:
            reason = f"Recommended: {', '.join(reasons[:2])}"
            if len(reasons) > 2:
                reason += f" (+{len(reasons)-2} more reasons)"
        
        return min(score, 1.0), reason
    
    def _get_highest_rank(self, ranks: List[str]) -> str:
        """Get the highest difficulty rank from a list"""
        rank_order = [QuestRank.EASY, QuestRank.NORMAL, QuestRank.MEDIUM, QuestRank.HARD, QuestRank.IMPOSSIBLE]
        
        for rank in reversed(rank_order):
            if rank in ranks:
                return rank
        
        return QuestRank.EASY
    
    def create_recommendations_embed(self, recommendations: List[Tuple[Quest, str, float]], user_name: str) -> discord.Embed:
        """Create embed for quest recommendations"""
        if not recommendations:
            embed = discord.Embed(
                title="🎯 Quest Recommendations",
                description="No personalized recommendations available yet. Complete some quests to get better suggestions!",
                color=discord.Color.orange()
            )
            return embed
        
        embed = discord.Embed(
            title=f"🎯 Quest Recommendations for {user_name}",
            description=f"Based on your quest history, here are {len(recommendations)} personalized recommendations:",
            color=discord.Color.green()
        )
        
        for i, (quest, reason, score) in enumerate(recommendations, 1):
            # Get confidence level
            if score >= 0.7:
                confidence = "⭐⭐⭐"
            elif score >= 0.5:
                confidence = "⭐⭐"
            else:
                confidence = "⭐"
            
            # Get rank emoji
            rank_emojis = {
                QuestRank.EASY: "🟢",
                QuestRank.NORMAL: "🔵",
                QuestRank.MEDIUM: "🟠", 
                QuestRank.HARD: "🔴",
                QuestRank.IMPOSSIBLE: "🟣"
            }
            rank_emoji = rank_emojis.get(quest.rank, "⚪")
            
            embed.add_field(
                name=f"{i}. {rank_emoji} {quest.title} ({quest.quest_id})",
                value=(
                    f"**{quest.category.title()}** • **{quest.rank.title()}** {confidence}\n"
                    f"{quest.description[:80]}{'...' if len(quest.description) > 80 else ''}\n"
                    f"*{reason}*"
                ),
                inline=False
            )
        
        embed.set_footer(text="Use /accept_quest <quest_id> to accept a recommended quest")
        return embed