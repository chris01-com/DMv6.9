import asyncio
import asyncpg
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class BountyManager:
    def __init__(self, database):
        self.db = database

    async def create_bounty(self, guild_id: int, creator_id: int, title: str, description: str, 
                           target_username: str, reward_text: str, images: Optional[List[str]] = None) -> str:
        """Create a new bounty"""
        bounty_id = str(uuid.uuid4())[:8]
        
        try:
            async with self.db.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO bounties (bounty_id, guild_id, creator_id, title, description, 
                                        target_username, reward_text, status, images, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'open', $8, $9)
                """, bounty_id, guild_id, creator_id, title, description, target_username, 
                     reward_text, images or [], datetime.utcnow())
                
                logger.info(f"✅ Created bounty {bounty_id} by user {creator_id} in guild {guild_id}")
                return bounty_id
                
        except Exception as e:
            logger.error(f"❌ Failed to create bounty: {e}")
            raise

    async def get_bounty(self, bounty_id: str, guild_id: int) -> Optional[Dict[str, Any]]:
        """Get bounty by ID"""
        try:
            async with self.db.pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM bounties 
                    WHERE bounty_id = $1 AND guild_id = $2
                """, bounty_id, guild_id)
                
                return dict(row) if row else None
                
        except Exception as e:
            logger.error(f"❌ Failed to get bounty {bounty_id}: {e}")
            return None

    async def list_bounties(self, guild_id: int, status: str = 'open') -> List[Dict[str, Any]]:
        """List bounties by status"""
        try:
            async with self.db.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT * FROM bounties 
                    WHERE guild_id = $1 AND status = $2
                    ORDER BY created_at DESC
                """, guild_id, status)
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"❌ Failed to list bounties: {e}")
            return []

    async def claim_bounty(self, bounty_id: str, guild_id: int, claimer_id: int) -> bool:
        """Claim an open bounty"""
        try:
            async with self.db.pool.acquire() as conn:
                # Check if bounty is still open
                bounty = await conn.fetchrow("""
                    SELECT status, creator_id FROM bounties 
                    WHERE bounty_id = $1 AND guild_id = $2
                """, bounty_id, guild_id)
                
                if not bounty or bounty['status'] != 'open':
                    return False
                
                if bounty['creator_id'] == claimer_id:
                    logger.warning(f"❌ User {claimer_id} tried to claim their own bounty {bounty_id}")
                    return False
                
                # Claim the bounty
                await conn.execute("""
                    UPDATE bounties 
                    SET status = 'claimed', claimed_by_id = $1, claimed_at = $2
                    WHERE bounty_id = $3 AND guild_id = $4 AND status = 'open'
                """, claimer_id, datetime.utcnow(), bounty_id, guild_id)
                
                logger.info(f"✅ User {claimer_id} claimed bounty {bounty_id}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to claim bounty {bounty_id}: {e}")
            return False

    async def submit_bounty(self, bounty_id: str, guild_id: int, proof_text: str, proof_images: Optional[List[str]] = None) -> bool:
        """Submit bounty completion proof"""
        try:
            async with self.db.pool.acquire() as conn:
                result = await conn.execute("""
                    UPDATE bounties 
                    SET status = 'submitted', proof_text = $1, proof_images = $2, submitted_at = $3
                    WHERE bounty_id = $4 AND guild_id = $5 AND status = 'claimed'
                """, proof_text, proof_images or [], datetime.utcnow(), bounty_id, guild_id)
                
                if result == "UPDATE 0":
                    return False
                
                logger.info(f"✅ Bounty {bounty_id} submitted for approval")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to submit bounty {bounty_id}: {e}")
            return False

    async def approve_bounty(self, bounty_id: str, guild_id: int) -> Optional[int]:
        """Approve bounty completion and return claimer_id"""
        try:
            async with self.db.pool.acquire() as conn:
                # Get bounty info including completion count
                bounty = await conn.fetchrow("""
                    SELECT claimed_by_id, completion_count FROM bounties 
                    WHERE bounty_id = $1 AND guild_id = $2 AND status = 'submitted'
                """, bounty_id, guild_id)
                
                if not bounty:
                    return None
                
                # Increment completion count
                new_completion_count = bounty['completion_count'] + 1
                
                if new_completion_count >= 2:
                    # Delete bounty after 2 completions
                    await conn.execute("""
                        DELETE FROM bounties 
                        WHERE bounty_id = $1 AND guild_id = $2
                    """, bounty_id, guild_id)
                    logger.info(f"✅ Bounty {bounty_id} completed 2 times and deleted")
                else:
                    # Reset bounty to open status with incremented count
                    await conn.execute("""
                        UPDATE bounties 
                        SET status = 'open', completion_count = $1, claimed_by_id = NULL,
                            proof_text = NULL, proof_images = ARRAY[]::TEXT[],
                            claimed_at = NULL, submitted_at = NULL, completed_at = $2
                        WHERE bounty_id = $3 AND guild_id = $4
                    """, new_completion_count, datetime.utcnow(), bounty_id, guild_id)
                    logger.info(f"✅ Bounty {bounty_id} completed ({new_completion_count}/2) and reset to open")
                
                return bounty['claimed_by_id']
                
        except Exception as e:
            logger.error(f"❌ Failed to approve bounty {bounty_id}: {e}")
            return None

    async def cancel_bounty(self, bounty_id: str, guild_id: int, user_id: int) -> bool:
        """Cancel a bounty (only by creator)"""
        try:
            async with self.db.pool.acquire() as conn:
                result = await conn.execute("""
                    UPDATE bounties 
                    SET status = 'cancelled'
                    WHERE bounty_id = $1 AND guild_id = $2 AND creator_id = $3 
                    AND status IN ('open', 'claimed')
                """, bounty_id, guild_id, user_id)
                
                if result == "UPDATE 0":
                    return False
                
                logger.info(f"✅ Bounty {bounty_id} cancelled by creator {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to cancel bounty {bounty_id}: {e}")
            return False

    async def get_user_bounties(self, guild_id: int, user_id: int) -> Dict[str, List[Dict[str, Any]]]:
        """Get all bounties related to a user"""
        try:
            async with self.db.pool.acquire() as conn:
                # Created bounties
                created = await conn.fetch("""
                    SELECT * FROM bounties 
                    WHERE guild_id = $1 AND creator_id = $2
                    ORDER BY created_at DESC
                """, guild_id, user_id)
                
                # Claimed bounties
                claimed = await conn.fetch("""
                    SELECT * FROM bounties 
                    WHERE guild_id = $1 AND claimed_by_id = $2
                    ORDER BY claimed_at DESC
                """, guild_id, user_id)
                
                return {
                    'created': [dict(row) for row in created],
                    'claimed': [dict(row) for row in claimed]
                }
                
        except Exception as e:
            logger.error(f"❌ Failed to get user bounties: {e}")
            return {'created': [], 'claimed': []}