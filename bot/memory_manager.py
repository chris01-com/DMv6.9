import asyncio
import weakref
import gc
import logging
from typing import Dict, List, Set
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class MemoryManager:
    """Advanced memory management for Discord bot views and caches"""
    
    def __init__(self, bot):
        self.bot = bot
        self.active_views = weakref.WeakSet()
        self.view_timestamps = {}
        self.cleanup_task = None
        self.max_view_age = 1800  # 30 minutes
        self.cleanup_interval = 300  # 5 minutes
    
    def start_memory_management(self):
        """Start the memory management background task"""
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("🧹 Memory management started")
    
    def stop_memory_management(self):
        """Stop the memory management background task"""
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
        logger.info("🧹 Memory management stopped")
    
    async def _cleanup_loop(self):
        """Main cleanup loop"""
        while True:
            try:
                await self._cleanup_stale_views()
                await self._cleanup_caches()
                await self._force_garbage_collection()
                
                await asyncio.sleep(self.cleanup_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error in memory cleanup loop: {e}")
                await asyncio.sleep(self.cleanup_interval)
    
    async def _cleanup_stale_views(self):
        """Clean up stale Discord views"""
        try:
            current_time = datetime.now()
            stale_views = []
            
            # Check for stale views in bot commands
            if hasattr(self.bot, 'cogs'):
                for cog in self.bot.cogs.values():
                    if hasattr(cog, 'active_leaderboard_views'):
                        views_to_remove = []
                        for view in cog.active_leaderboard_views:
                            view_id = id(view)
                            if view_id in self.view_timestamps:
                                age = current_time - self.view_timestamps[view_id]
                                if age.total_seconds() > self.max_view_age:
                                    views_to_remove.append(view)
                                    stale_views.append(view_id)
                        
                        for view in views_to_remove:
                            try:
                                cog.active_leaderboard_views.remove(view)
                                self.view_timestamps.pop(id(view), None)
                            except (ValueError, KeyError):
                                pass
            
            # Also check global active_leaderboard_views if it exists
            if hasattr(self.bot, 'commands') and hasattr(self.bot.commands, 'active_leaderboard_views'):
                views_to_remove = []
                for view in self.bot.commands.active_leaderboard_views[:]:
                    view_id = id(view)
                    if view_id in self.view_timestamps:
                        age = current_time - self.view_timestamps[view_id]
                        if age.total_seconds() > self.max_view_age:
                            views_to_remove.append(view)
                            stale_views.append(view_id)
                
                for view in views_to_remove:
                    try:
                        self.bot.commands.active_leaderboard_views.remove(view)
                        self.view_timestamps.pop(id(view), None)
                    except (ValueError, KeyError):
                        pass
            
            if stale_views:
                logger.info(f"🧹 Cleaned up {len(stale_views)} stale views")
                
        except Exception as e:
            logger.error(f"❌ Error cleaning up stale views: {e}")
    
    async def _cleanup_caches(self):
        """Clean up various caches"""
        try:
            cleanup_count = 0
            
            # Clean up leaderboard manager caches
            if hasattr(self.bot, 'leaderboard_manager'):
                lm = self.bot.leaderboard_manager
                if hasattr(lm, '_mentor_cache') and hasattr(lm, '_cache_timestamp'):
                    current_time = datetime.now().timestamp()
                    expired_keys = [
                        key for key, timestamp in lm._cache_timestamp.items()
                        if current_time - timestamp > lm._cache_duration
                    ]
                    
                    for key in expired_keys:
                        lm._mentor_cache.pop(key, None)
                        lm._cache_timestamp.pop(key, None)
                        cleanup_count += 1
            
            # Clean up other manager caches
            for manager_name in ['quest_manager', 'role_reward_manager', 'mentor_channel_manager']:
                if hasattr(self.bot, manager_name):
                    manager = getattr(self.bot, manager_name)
                    if hasattr(manager, 'clear_expired_cache'):
                        await manager.clear_expired_cache()
                        cleanup_count += 1
            
            if cleanup_count > 0:
                logger.debug(f"🧹 Cleaned up {cleanup_count} cache entries")
                
        except Exception as e:
            logger.error(f"❌ Error cleaning up caches: {e}")
    
    async def _force_garbage_collection(self):
        """Force garbage collection to free up memory"""
        try:
            # Count objects before collection
            before_count = len(gc.get_objects())
            
            # Force garbage collection
            collected = gc.collect()
            
            # Count objects after collection
            after_count = len(gc.get_objects())
            
            if collected > 0:
                logger.debug(f"🧹 Garbage collection: freed {collected} objects, {before_count - after_count} total objects removed")
                
        except Exception as e:
            logger.error(f"❌ Error during garbage collection: {e}")
    
    def register_view(self, view):
        """Register a view for memory management"""
        self.active_views.add(view)
        self.view_timestamps[id(view)] = datetime.now()
    
    def unregister_view(self, view):
        """Unregister a view from memory management"""
        try:
            self.active_views.discard(view)
            self.view_timestamps.pop(id(view), None)
        except Exception as e:
            logger.debug(f"Error unregistering view: {e}")
    
    def get_memory_stats(self) -> Dict:
        """Get current memory management statistics"""
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            
            return {
                'active_views': len(self.active_views),
                'tracked_timestamps': len(self.view_timestamps),
                'memory_usage_mb': memory_info.rss / 1024 / 1024,
                'memory_percent': process.memory_percent(),
                'gc_objects': len(gc.get_objects())
            }
        except Exception as e:
            logger.error(f"❌ Error getting memory stats: {e}")
            return {'error': str(e)}
    
    async def emergency_cleanup(self):
        """Perform emergency memory cleanup"""
        try:
            logger.warning("🚨 Performing emergency memory cleanup")
            
            # Clear all view caches immediately
            self.active_views.clear()
            self.view_timestamps.clear()
            
            # Clear all manager caches
            if hasattr(self.bot, 'leaderboard_manager'):
                lm = self.bot.leaderboard_manager
                if hasattr(lm, '_mentor_cache'):
                    lm._mentor_cache.clear()
                if hasattr(lm, '_cache_timestamp'):
                    lm._cache_timestamp.clear()
            
            # Force aggressive garbage collection
            for _ in range(3):
                gc.collect()
            
            logger.info("✅ Emergency cleanup complete")
            
        except Exception as e:
            logger.error(f"❌ Error during emergency cleanup: {e}")