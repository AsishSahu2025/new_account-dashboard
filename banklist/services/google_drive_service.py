from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from django.conf import settings
import calendar
from datetime import datetime
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
import io


class GoogleDriveService:
    """Service for managing Google Drive folders using OAuth"""

    SCOPES = ['https://www.googleapis.com/auth/drive']

    # Default subfolders created inside every company folder
    COMPANY_SUBFOLDERS = [
        'Reconciliation_Receipt',
        'Ledger',
        'Bank_Statement',
        'Billing_Receipt',
    ]

    def __init__(self):
        """Initialize Google Drive service with OAuth"""
        try:
            self.creds = Credentials(
                token=None,
                refresh_token=settings.GOOGLE_REFRESH_TOKEN,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=settings.GOOGLE_CLIENT_ID,
                client_secret=settings.GOOGLE_CLIENT_SECRET,
                scopes=self.SCOPES
            )

            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())

            self.service = build('drive', 'v3', credentials=self.creds)
            print("✅ Google Drive service initialized")

        except Exception as e:
            print(f"❌ Failed to initialize Google Drive service: {e}")
            self.service = None

    # ─────────────────────────────────────────────────────────────────────────
    # FOLDER OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────

    def create_folder(self, folder_name, parent_folder_id=None):
        """
        Create a folder in Google Drive.
        Returns folder ID if successful, None otherwise.
        """
        if not self.service:
            return None

        try:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }

            if parent_folder_id:
                file_metadata['parents'] = [parent_folder_id]

            folder = self.service.files().create(
                body=file_metadata,
                fields='id, name, webViewLink'
            ).execute()

            print(f"✅ Created folder: {folder_name} (ID: {folder.get('id')})")
            return folder.get('id')

        except HttpError as error:
            print(f"❌ Error creating folder {folder_name}: {error}")
            return None

    def folder_exists(self, folder_name, parent_folder_id=None):
        """
        Check if a folder exists.
        Returns folder ID if exists, None otherwise.
        """
        if not self.service:
            return None

        try:
            query = (
                f"name='{folder_name}' "
                f"and mimeType='application/vnd.google-apps.folder' "
                f"and trashed=false"
            )

            if parent_folder_id:
                query += f" and '{parent_folder_id}' in parents"

            response = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)',
                pageSize=1
            ).execute()

            files = response.get('files', [])
            return files[0].get('id') if files else None

        except HttpError as error:
            print(f"❌ Error checking folder existence: {error}")
            return None

    def delete_folder(self, folder_id: str) -> bool:
        """
        Permanently delete a folder and ALL its contents from Google Drive.
        Returns True on success, False on failure.
        """
        if not self.service:
            print("❌ Drive service not initialized — cannot delete folder")
            return False

        try:
            self.service.files().delete(fileId=folder_id).execute()
            print(f"✅ Drive folder {folder_id} deleted successfully")
            return True
        except HttpError as e:
            print(f"❌ Failed to delete Drive folder {folder_id}: {e}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error deleting Drive folder {folder_id}: {e}")
            return False

    def get_folder_link(self, folder_id):
        """Get web view link for a folder."""
        if not self.service:
            return None

        try:
            folder = self.service.files().get(
                fileId=folder_id,
                fields='webViewLink'
            ).execute()
            return folder.get('webViewLink')
        except HttpError as error:
            print(f"❌ Error getting folder link: {error}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # COMPANY & BANK FOLDER STRUCTURE
    # ─────────────────────────────────────────────────────────────────────────

    def get_or_create_company_folder(self, company_name):
        """
        Get or create the company's root folder in Drive,
        along with its default subfolders.
        """
        if not self.service:
            return None

        try:
            company_folder_id = self.folder_exists(company_name, parent_folder_id=None)

            if not company_folder_id:
                company_folder_id = self.create_folder(company_name, parent_folder_id=None)
                print(f"🏢 Created company folder: {company_name}")
            else:
                print(f"🏢 Company folder already exists: {company_name}")

            if not company_folder_id:
                return None

            subfolders = {}
            for subfolder_name in self.COMPANY_SUBFOLDERS:
                subfolder_id = self.folder_exists(subfolder_name, company_folder_id)
                if not subfolder_id:
                    subfolder_id = self.create_folder(subfolder_name, company_folder_id)
                    print(f"  📂 Created subfolder: {subfolder_name}")
                else:
                    print(f"  📂 Subfolder already exists: {subfolder_name}")
                if subfolder_id:
                    subfolders[subfolder_name] = subfolder_id

            return {
                'company_folder_id': company_folder_id,
                'subfolders': subfolders,
            }

        except Exception as error:
            print(f"❌ Error getting/creating company folder '{company_name}': {error}")
            return None

    def create_bank_folder_structure(self, bank_name, company_name=None, current_year=None):
        """
        Create folder structure for a bank under the company's Drive folder.

        Structure:
          Company Folder/
            └── Bank_Statement/
                └── Bank Name - Account Holder - Account Number/
                    └── Statement/

        Returns dict with folder IDs and status.
        """
        if not self.service:
            return {
                'success': False,
                'message': 'Google Drive service not initialized',
                'bank_folder_id': None,
                'statement_folder_id': None,
                'month_folders': []
            }

        try:
            # Resolve parent folder
            if company_name:
                company_result = self.get_or_create_company_folder(company_name)
                if not company_result:
                    return {
                        'success': False,
                        'message': f'Failed to get/create company folder for "{company_name}"',
                        'bank_folder_id': None,
                        'statement_folder_id': None,
                        'month_folders': []
                    }
                parent_folder_id = company_result['subfolders'].get(
                    'Bank_Statement', company_result['company_folder_id']
                )
            else:
                parent_folder_id = settings.GOOGLE_DRIVE_PARENT_FOLDER_ID

            # Create/get bank folder
            bank_folder_id = self.folder_exists(bank_name, parent_folder_id)
            if not bank_folder_id:
                bank_folder_id = self.create_folder(bank_name, parent_folder_id)
                print(f"📁 Created new bank folder: {bank_name}")
            else:
                print(f"📁 Bank folder already exists: {bank_name}")

            if not bank_folder_id:
                return {
                    'success': False,
                    'message': 'Failed to create bank folder',
                    'bank_folder_id': None,
                    'statement_folder_id': None,
                    'month_folders': []
                }

            # Create/get Statement subfolder
            statement_folder_id = self.folder_exists('Statement', bank_folder_id)
            if not statement_folder_id:
                statement_folder_id = self.create_folder('Statement', bank_folder_id)
                print(f"📁 Created Statement folder for: {bank_name}")
            else:
                print(f"📁 Statement folder already exists for: {bank_name}")

            if not statement_folder_id:
                return {
                    'success': False,
                    'message': 'Failed to create Statement folder',
                    'bank_folder_id': bank_folder_id,
                    'statement_folder_id': None,
                    'month_folders': []
                }

            bank_folder      = self.service.files().get(fileId=bank_folder_id,      fields='webViewLink').execute()
            statement_folder = self.service.files().get(fileId=statement_folder_id, fields='webViewLink').execute()

            return {
                'success': True,
                'message': f'Successfully created folder structure for {bank_name}',
                'bank_folder_id': bank_folder_id,
                'bank_folder_link': bank_folder.get('webViewLink'),
                'statement_folder_id': statement_folder_id,
                'statement_folder_link': statement_folder.get('webViewLink'),
                'month_folders': [],
                'total_folders_created': 2
            }

        except Exception as error:
            print(f"❌ Error creating bank folder structure: {error}")
            return {
                'success': False,
                'message': str(error),
                'bank_folder_id': None,
                'statement_folder_id': None,
                'month_folders': []
            }

    # ─────────────────────────────────────────────────────────────────────────
    # FILE OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────

    def upload_file(self, file_obj, file_name, folder_id, mime_type):
        """
        Upload a file to a specific Drive folder.
        Returns dict with file ID and link, or None on failure.
        """
        if not self.service:
            return None

        try:
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }

            media = MediaIoBaseUpload(
                io.BytesIO(file_obj.read()),
                mimetype=mime_type,
                resumable=True
            )

            uploaded_file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()

            print(f"✅ Uploaded file: {file_name} (ID: {uploaded_file.get('id')})")
            return {
                'file_id':   uploaded_file.get('id'),
                'file_name': uploaded_file.get('name'),
                'file_link': uploaded_file.get('webViewLink')
            }

        except HttpError as error:
            print(f"❌ Error uploading file {file_name}: {error}")
            return None

    def list_files(self, folder_id, page_size=200):
        """List files inside a Drive folder."""
        if not self.service:
            return []

        try:
            response = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                spaces='drive',
                fields='files(id, name, mimeType, webViewLink, createdTime)',
                orderBy='createdTime desc',
                pageSize=page_size,
            ).execute()
            return response.get('files', [])
        except HttpError as error:
            print(f"❌ Error listing files for folder {folder_id}: {error}")
            return []

    def download_file(self, file_id):
        """Download a file from Google Drive and return bytes."""
        if not self.service:
            return None

        try:
            request = self.service.files().get_media(fileId=file_id)
            file_buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(file_buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return file_buffer.getvalue()
        except HttpError as error:
            print(f"❌ Error downloading file {file_id}: {error}")
            return None


# Singleton instance
drive_service = GoogleDriveService()