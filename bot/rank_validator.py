"""
Enhanced rank validation system for Discord bot
Validates quest completions, previous rank requirements, and mentorship requirements
"""

import logging
from typing import Dict, List, Optional, Tuple
from bot.sql_database import SQLDatabase

logger = logging.getLogger(__name__)

class RankValidator:
    """Validates enhanced rank requirements including quests, progression, and mentorship"""
    
    def __init__(self, database: SQLDatabase):
        self.database = database
        
    async def validate_rank_requirements(self, user_id: int, guild_id: int, target_role_id: int, 
                                       member_roles: List[int], user_points: int) -> Tuple[bool, List[str]]:
        """
        Validate all requirements for a rank request
        Returns: (is_valid, list_of_missing_requirements)
        """
        from bot.utils import ENHANCED_RANK_REQUIREMENTS
        
        errors = []
        
        if target_role_id not in ENHANCED_RANK_REQUIREMENTS:
            errors.append("Invalid rank requested")
            return False, errors
            
        requirements = ENHANCED_RANK_REQUIREMENTS[target_role_id]
        
        # 1. Check points requirement
        if user_points < requirements["points"]:
            needed_points = requirements["points"] - user_points
            errors.append(f"Need {needed_points} more points (have {user_points}, need {requirements['points']})")
        
        # 2. Check previous rank requirement  
        if requirements["previous_rank"]:
            if requirements["previous_rank"] not in member_roles:
                prev_rank_name = ENHANCED_RANK_REQUIREMENTS[requirements["previous_rank"]]["name"]
                errors.append(f"Must have {prev_rank_name} rank first")
        
        # 3. Check quest requirements using existing database
        quest_errors = await self._validate_quest_requirements(user_id, guild_id, requirements["quest_requirements"])
        errors.extend(quest_errors)
        
        return len(errors) == 0, errors
    
    async def _validate_quest_requirements(self, user_id: int, guild_id: int, 
                                         quest_requirements: Dict[str, int]) -> List[str]:
        """Validate quest completion requirements using difficulty"""
        errors = []
        
        if not quest_requirements:
            return errors
            
        try:
            async with self.database.pool.acquire() as conn:
                for difficulty, required_count in quest_requirements.items():
                    # Count approved quests of this difficulty (using rank column)
                    completed_count = await conn.fetchval('''
                        SELECT COUNT(*) FROM quest_progress qp
                        JOIN quests q ON qp.quest_id = q.quest_id AND qp.guild_id = q.guild_id
                        WHERE qp.user_id = $1 AND qp.guild_id = $2 
                        AND qp.status = 'approved' AND q.rank = $3
                    ''', user_id, guild_id, difficulty)
                    
                    completed_count = completed_count or 0
                    
                    if completed_count < required_count:
                        missing = required_count - completed_count
                        errors.append(f"Must complete {missing} more {difficulty} quest{'s' if missing != 1 else ''} (completed: {completed_count}, need: {required_count})")
        
        except Exception as e:
            logger.error(f"Error validating quest requirements: {e}")
            errors.append("Error checking quest requirements")
            
        return errors
    

    
    async def get_rank_progress_summary(self, user_id: int, guild_id: int, target_role_id: int, 
                                      member_roles: List[int], user_points: int) -> str:
        """Get a detailed progress summary for a rank"""
        from bot.utils import ENHANCED_RANK_REQUIREMENTS
        
        if target_role_id not in ENHANCED_RANK_REQUIREMENTS:
            return "Invalid rank"
            
        requirements = ENHANCED_RANK_REQUIREMENTS[target_role_id]
        
        summary_lines = []
        summary_lines.append(f"**Requirements for {requirements['name']}:**")
        
        # Points
        points_status = "✅" if user_points >= requirements["points"] else "❌"
        summary_lines.append(f"{points_status} Points: {user_points}/{requirements['points']}")
        
        # Previous rank
        if requirements["previous_rank"]:
            prev_rank_name = ENHANCED_RANK_REQUIREMENTS[requirements["previous_rank"]]["name"]
            prev_status = "✅" if requirements["previous_rank"] in member_roles else "❌"
            summary_lines.append(f"{prev_status} Previous Rank: {prev_rank_name}")
        
        # Quest requirements
        if requirements["quest_requirements"]:
            summary_lines.append("**Quest Requirements:**")
            try:
                async with self.database.pool.acquire() as conn:
                    for difficulty, required_count in requirements["quest_requirements"].items():
                        completed_count = await conn.fetchval('''
                            SELECT COUNT(*) FROM quest_progress qp
                            JOIN quests q ON qp.quest_id = q.quest_id AND qp.guild_id = q.guild_id
                            WHERE qp.user_id = $1 AND qp.guild_id = $2 
                            AND qp.status = 'approved' AND q.rank = $3
                        ''', user_id, guild_id, difficulty)
                        
                        completed_count = completed_count or 0
                        quest_status = "✅" if completed_count >= required_count else "❌"
                        summary_lines.append(f"{quest_status} {difficulty} Quests: {completed_count}/{required_count}")
            except Exception as e:
                logger.error(f"Error getting quest progress: {e}")
                summary_lines.append("❌ Error checking quest progress")

        
        return "\n".join(summary_lines)