"""Planning Center Online API service."""

import requests
import traceback
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from loguru import logger

from ..core.config import PlanningCenterConfig

@dataclass
class PCOArrangement:
    """Represents an arrangement from Planning Center Online."""
    id: str
    sequence: List[str]
    bpm: int
    meter: str

@dataclass
class PCOSong:
    """Represents a song from Planning Center Online."""
    id: str
    title: str
    author: Optional[str] = None
    ccli_number: Optional[str] = None
    themes: List[str] = None
    key_name: Optional[str] = None
    item_id: Optional[str] = None
    arrangement: Optional[PCOArrangement] = None

    def __post_init__(self):
        if self.themes is None:
            self.themes = []

@dataclass
class PCOServicePlan:
    """Represents a service plan from Planning Center Online."""
    id: str
    title: str
    date: datetime
    songs: List[PCOSong]
    service_type: Optional[str] = None

@dataclass
class PCOFolder:
    """Represents a folder from Planning Center Online."""
    id: str
    name: str
    parent_id: Optional[str] = None

@dataclass
class PCOServiceType:
    """Represents a service type from Planning Center Online."""
    id: str
    name: str
    folder_id: str

class PlanningCenterService:
    """Service for interacting with Planning Center Online API."""

    def __init__(self, config: PlanningCenterConfig):
        """Initialize the PCO service.

        Args:
            config: Planning Center configuration
        """
        self.config = config
        self.base_url = config.base_url.rstrip('/')
        self.session = requests.Session()

        # Set up authentication
        if config.application_id and config.secret:
            self.session.auth = (config.application_id, config.secret)
            logger.info("PCO authentication configured")
        else:
            logger.warning("PCO credentials not configured")

    def get_service_plans(self, days_ahead: int = 30) -> List[PCOServicePlan]:
        """Get upcoming service plans.

        Args:
            days_ahead: Number of days to look ahead

        Returns:
            List of service plans
        """
        try:
            # Get service types first
            service_types = self._get_all_service_types()
            if not service_types:
                logger.warning("No service types found")
                return []

            plans = []
            for service_type in service_types:
                type_plans = self._get_plans_for_service_type(service_type['id'])
                plans.extend(type_plans)

            # Filter to upcoming plans
            now = datetime.now()
            upcoming_plans = [
                plan for plan in plans
                if plan.date >= now
            ]

            # Sort by date
            upcoming_plans.sort(key=lambda x: x.date)

            logger.info(f"Found {len(upcoming_plans)} upcoming service plans")
            return upcoming_plans[:10]  # Return first 10

        except Exception as e:
            logger.error(f"Failed to get service plans: {e}")
            return []

    def get_folders(self) -> List[PCOFolder]:
        """Get all folders from the organization.

        Returns:
            List of folders
        """
        url = f"{self.base_url}/services/v2/folders"
        params = {'per_page': 500}

        try:
            response = self.session.get(url, params=params)
            if response is None:
                logger.error("Response object is None")
                return []
                
            if not hasattr(response, 'json'):
                logger.error(f"Response doesn't have json method: {type(response)}")
                return []
            
            data = response.json()
            if data is None:
                logger.warning("Response JSON returned None")
                return []

            if not isinstance(data, dict):
                logger.warning(f"Response JSON is not a dict, it's: {type(data)}")
                return []

            folders = []
            data_list = data.get('data', [])
            if data_list is None:
                data_list = []
            
            # Log all folder IDs for debugging
            all_ids = [f['id'] for f in data_list if 'id' in f]
            logger.info(f"API returned {len(all_ids)} folder IDs: {all_ids}")
            
            # Check if Summers Corner is in the response
            if '1550568' in all_ids:
                logger.info("✓ Summers Corner Campus (1550568) IS in the API response")
            else:
                logger.warning("✗ Summers Corner Campus (1550568) NOT in API response - may need special handling")
            
            skipped_count = 0
            for folder_data in data_list:
                if folder_data is None:
                    logger.warning("Skipped: folder_data is None")
                    skipped_count += 1
                    continue
                    
                try:
                    # Safely handle potential None attributes
                    attributes = folder_data.get('attributes')
                    if attributes is None:
                        # Try alternative fields or use defaults
                        folder_id = folder_data.get('id', 'UNKNOWN')
                        folder_name = folder_data.get('name', f'Folder {folder_id}')
                        logger.warning(f"Folder {folder_id}: attributes is None, using fallback name: {folder_name}")
                    else:
                        folder_name = attributes.get('name', 'Unknown')
                    
                    relationships = folder_data.get('relationships')
                    parent_id = None
                    if relationships:
                        parent_data = relationships.get('parent', {}).get('data')
                        if parent_data:
                            parent_id = parent_data.get('id')
                    
                    folder = PCOFolder(
                        id=folder_data['id'],
                        name=folder_name,
                        parent_id=parent_id
                    )
                    folders.append(folder)
                    
                    # Log Summers Corner specifically
                    if folder.id == '1550568':
                        logger.info(f"✓ Created PCOFolder for Summers Corner: {folder.name}")
                        
                except (KeyError, TypeError, AttributeError) as e:
                    folder_id = folder_data.get('id', 'UNKNOWN') if folder_data else 'NULL'
                    logger.warning(f"Skipped folder {folder_id}: {type(e).__name__}: {e}")
                    skipped_count += 1
                    continue

            logger.info(f"Found {len(folders)} folders total after parsing (skipped {skipped_count} folders)")
            logger.debug(f"Returning folder IDs: {[f.id for f in folders]}")
            return folders

        except Exception as e:
            logger.error(f"Failed to get folders: {type(e).__name__}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def get_service_types_for_folder(self, folder_id: str) -> List[PCOServiceType]:
        """Get service types for a specific folder.

        Args:
            folder_id: The ID of the folder

        Returns:
            List of service types in that folder
        """
        url = f"{self.base_url}/services/v2/service_types"
        params = {
            'where[parent_id]': folder_id,
            'per_page': 100
        }

        try:
            response = self.session.get(url, params=params)
            data = response.json()

            if not data or not isinstance(data, dict):
                return []

            service_types = []
            data_list = data.get('data', [])
            
            for st_data in data_list:
                if st_data is None:
                    continue
                    
                try:
                    st = PCOServiceType(
                        id=st_data['id'],
                        name=st_data['attributes'].get('name', 'Unknown'),
                        folder_id=folder_id
                    )
                    service_types.append(st)
                except (KeyError, TypeError, AttributeError) as e:
                    logger.debug(f"Skipped malformed service type data: {e}")
                    continue

            logger.info(f"Found {len(service_types)} service types for folder {folder_id}")
            return service_types

        except Exception as e:
            logger.error(f"Failed to get service types for folder {folder_id}: {e}", exc_info=True)
            return []

    def _get_all_service_types(self) -> List[Dict[str, Any]]:
        """Get available service types."""
        url = f"{self.base_url}/services/v2/service_types"
        try:
            response = self.session.get(url)
            response.raise_for_status()
            data = response.json()
            return data.get('data', [])
        except Exception as e:
            logger.error(f"Failed to get service types: {e}")
            return []

    def get_plans_for_service_type(self, service_type_id: str, days_ahead: int = 30) -> List[PCOServicePlan]:
        """Get upcoming plans for a specific service type.

        Args:
            service_type_id: The ID of the service type
            days_ahead: Number of days to look ahead

        Returns:
            List of service plans for this service type
        """
        return self._get_plans_for_service_type(service_type_id)

    def _get_plans_for_service_type(self, service_type_id: str) -> List[PCOServicePlan]:
        """Get service plans for a specific service type."""
        url = f"{self.base_url}/services/v2/service_types/{service_type_id}/plans"
        params = {
            'filter': 'future',
            'per_page': 50
        }

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            plans = []
            for plan_data in data.get('data', []):
                # Use lightweight parsing - don't fetch songs yet
                plan = self._parse_service_plan_lightweight(plan_data)
                if plan:
                    plans.append(plan)

            return plans

        except Exception as e:
            logger.error(f"Failed to get plans for service type {service_type_id}: {e}")
            return []

    def _parse_service_plan_lightweight(self, plan_data: Dict[str, Any]) -> Optional[PCOServicePlan]:
        """Parse a service plan WITHOUT fetching songs (lightweight version for listing)."""
        try:
            attributes = plan_data.get('attributes', {})
            relationships = plan_data.get('relationships', {})

            # Parse date
            date_str = attributes.get('dates', attributes.get('date'))
            if not date_str:
                return None

            plan_date = self._parse_date(date_str)
            if not plan_date:
                logger.warning(f"Could not parse date: {date_str}")
                return None

            # Create plan without songs - songs will be fetched when plan is selected
            plan = PCOServicePlan(
                id=plan_data['id'],
                title=attributes.get('title', f"Service {plan_date.strftime('%Y-%m-%d')}"),
                date=plan_date,
                songs=[],  # Empty for now - will be populated when user selects this plan
                service_type=relationships.get('service_type', {}).get('data', {}).get('id')
            )

            return plan

        except Exception as e:
            logger.error(f"Failed to parse service plan: {e}")
            return None

    def _populate_plan_songs(self, plan: PCOServicePlan, service_type_id: str) -> None:
        """Populate songs for a plan (called when plan is actually selected)."""
        songs = self._get_songs_from_plan(plan.id, service_type_id)
        plan.songs = songs

    def _parse_service_plan(self, plan_data: Dict[str, Any]) -> Optional[PCOServicePlan]:
        """Parse a service plan from PCO API response."""
        try:
            attributes = plan_data.get('attributes', {})
            relationships = plan_data.get('relationships', {})

            # Parse date
            date_str = attributes.get('dates', attributes.get('date'))
            if not date_str:
                return None

            plan_date = self._parse_date(date_str)
            if not plan_date:
                logger.warning(f"Could not parse date: {date_str}")
                return None

            # Get songs from plan items
            service_type_id = relationships.get('service_type', {}).get('data', {}).get('id')
            songs = self._get_songs_from_plan(plan_data['id'], service_type_id)

            plan = PCOServicePlan(
                id=plan_data['id'],
                title=attributes.get('title', f"Service {plan_date.strftime('%Y-%m-%d')}"),
                date=plan_date,
                songs=songs,
                service_type=relationships.get('service_type', {}).get('data', {}).get('id')
            )

            return plan

        except Exception as e:
            logger.error(f"Failed to parse service plan: {e}")
            return None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse a date string in various formats.
        
        Args:
            date_str: Date string in ISO format, human-readable format, or other common formats
            
        Returns:
            Parsed datetime object or None if parsing fails
        """
        if not date_str:
            return None

        # Try ISO format first
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

        # Try common human-readable formats
        date_formats = [
            "%B %d, %Y",      # April 19, 2026
            "%b %d, %Y",      # Apr 19, 2026
            "%m/%d/%Y",       # 04/19/2026
            "%Y-%m-%d",       # 2026-04-19
            "%d-%m-%Y",       # 19-04-2026
            "%A, %B %d, %Y",  # Saturday, April 19, 2026
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue

        logger.debug(f"Could not parse date with any format: {date_str}")
        return None

    def _get_songs_from_plan(self, plan_id: str, service_type_id: Optional[str] = None) -> List[PCOSong]:
        """Get songs from a service plan, preserving order, key information, and arrangement sequence."""
        url = f"{self.base_url}/services/v2/plans/{plan_id}/items"
        songs = []

        try:
            response = self.session.get(url)
            response.raise_for_status()
            data = response.json()

            for item in data.get('data', []):
                attributes = item.get('attributes', {})
                relationships = item.get('relationships', {})

                # Only process song items
                if attributes.get('item_type') != 'song':
                    continue

                # Get song details
                song_data = relationships.get('song', {}).get('data')
                if song_data:
                    song = self._get_song_details(song_data['id'])
                    if song:
                        # Capture the key_name from the item (not the song details)
                        song.key_name = attributes.get('key_name')
                        song.item_id = item['id']
                        
                        # Fetch arrangement if service_type_id is available
                        if service_type_id:
                            song.arrangement = self._get_arrangement_for_item(service_type_id, plan_id, item['id'])
                        
                        songs.append(song)

        except Exception as e:
            logger.error(f"Failed to get songs from plan {plan_id}: {e}")

        return songs

    def _get_song_details(self, song_id: str) -> Optional[PCOSong]:
        """Get detailed song information."""
        url = f"{self.base_url}/services/v2/songs/{song_id}"

        try:
            response = self.session.get(url)
            response.raise_for_status()
            data = response.json()

            attributes = data.get('data', {}).get('attributes', {})

            song = PCOSong(
                id=song_id,
                title=attributes.get('title', 'Unknown Song'),
                author=attributes.get('author'),
                ccli_number=attributes.get('ccli_number'),
                themes=attributes.get('themes', [])
            )

            return song

        except Exception as e:
            logger.error(f"Failed to get song details for {song_id}: {e}")
            return None

    def _get_arrangement_for_item(self, service_type_id: str, plan_id: str, item_id: str) -> Optional[PCOArrangement]:
        """Get arrangement data for a service plan item."""
        url = f"{self.base_url}/services/v2/service_types/{service_type_id}/plans/{plan_id}/items/{item_id}/arrangement"

        try:
            response = self.session.get(url)
            response.raise_for_status()
            data = response.json()

            attributes = data.get('data', {}).get('attributes', {})
            arrangement = PCOArrangement(
                id=data.get('data', {}).get('id', ''),
                sequence=attributes.get('sequence', []),
                bpm=attributes.get('bpm', 120),
                meter=attributes.get('meter', '4/4')
            )
            return arrangement

        except Exception as e:
            logger.error(f"Failed to get arrangement for item {item_id}: {e}")
            return None