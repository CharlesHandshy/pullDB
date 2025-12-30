"""E2E tests for restore page backup loading.

Tests that:
1. Customer search works without JS errors
2. Backup list loads for selected customer
3. "Available Backups for {customer}" title appears
4. At least one backup row is displayed (when data exists)
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
class TestRestoreBackupLoading:
    """Tests for restore page backup loading functionality."""

    def test_customer_search_and_backup_loading(
        self, logged_in_page: Page, base_url: str
    ) -> None:
        """Test that selecting a customer loads backups without JS errors.
        
        This test verifies:
        1. No JS errors occur during customer selection
        2. The backup list title updates to show the selected customer
        3. The backup list container becomes visible
        """
        page = logged_in_page
        js_errors: list[str] = []

        # Capture any console errors
        page.on("console", lambda msg: js_errors.append(msg.text) if msg.type == "error" else None)

        # Navigate to restore page
        page.goto(f"{base_url}/web/restore")
        page.wait_for_load_state("networkidle")

        # Verify restore page loaded
        expect(page.locator("h1.page-title")).to_have_text("New Restore Job")

        # Verify customer search input exists
        customer_search = page.locator("#customer-search")
        expect(customer_search).to_be_visible()

        # Type "tanner" in customer search
        customer_search.fill("tanner")
        
        # Wait for search results to appear (debounce + API call)
        page.wait_for_timeout(500)  # Account for 300ms debounce + network
        
        # Wait for results container to be visible
        results_container = page.locator("#customer-results-container")
        expect(results_container).to_have_class(re.compile(r"is-open"))

        # Check if there are any customer results
        result_items = page.locator(".customer-result-item")
        result_count = result_items.count()
        
        if result_count > 0:
            # Click first customer result
            result_items.first.click()
            
            # Wait for backup loading
            page.wait_for_timeout(500)
            
            # Verify backup list container is visible
            backup_container = page.locator("#backup-list-container")
            expect(backup_container).to_have_class(re.compile(r"is-visible"))
            
            # Verify backup list title shows customer name
            backup_title = page.locator("#backup-list-title")
            expect(backup_title).to_contain_text("Available Backups for")
        else:
            # No customer found - that's okay for simulation mode
            # Just verify no JS errors occurred
            pass

        # Assert no JavaScript errors occurred (the main bug we're fixing)
        assert len(js_errors) == 0, f"JavaScript errors detected: {js_errors}"

    def test_date_from_input_exists(
        self, logged_in_page: Page, base_url: str
    ) -> None:
        """Test that date-from input exists and has a default value.
        
        This verifies the DOM element that was causing the null reference error
        is present in the page.
        """
        page = logged_in_page

        # Navigate to restore page
        page.goto(f"{base_url}/web/restore")
        page.wait_for_load_state("networkidle")

        # Verify date-from input exists
        date_input = page.locator("#date-from")
        expect(date_input).to_be_visible()
        
        # Verify it has a value (default should be 7 days ago)
        date_value = date_input.input_value()
        assert date_value, "date-from input should have a default value"
        
        # Verify format is YYYY-MM-DD
        import re
        assert re.match(r"\d{4}-\d{2}-\d{2}", date_value), f"Expected YYYY-MM-DD format, got: {date_value}"

    def test_no_js_errors_on_tab_switch(
        self, logged_in_page: Page, base_url: str
    ) -> None:
        """Test that switching between Customer and QA Template tabs works without errors."""
        page = logged_in_page
        js_errors: list[str] = []

        page.on("console", lambda msg: js_errors.append(msg.text) if msg.type == "error" else None)

        # Navigate to restore page
        page.goto(f"{base_url}/web/restore")
        page.wait_for_load_state("networkidle")

        # Click QA Template tab
        qa_tab = page.locator('[data-tab="qatemplate"]')
        qa_tab.click()
        page.wait_for_timeout(300)

        # Verify QA tab is active
        expect(qa_tab).to_have_class(re.compile(r"active"))

        # Switch back to Customer tab
        customer_tab = page.locator('[data-tab="customer"]')
        customer_tab.click()
        page.wait_for_timeout(300)

        # Verify Customer tab is active
        expect(customer_tab).to_have_class(re.compile(r"active"))

        # Assert no JavaScript errors
        assert len(js_errors) == 0, f"JavaScript errors on tab switch: {js_errors}"


@pytest.mark.e2e
class TestRestoreBackupLoadingWithTanner:
    """Tests specifically for loading Tanner customer backups.
    
    These tests require the simulation to include 'tanner' as a customer
    with available backups.
    """

    def test_tanner_backup_rows_appear(
        self, logged_in_page: Page, base_url: str
    ) -> None:
        """Test that selecting Tanner loads backup rows.
        
        This test verifies the complete flow from customer selection
        to backup row display.
        """
        page = logged_in_page
        js_errors: list[str] = []

        page.on("console", lambda msg: js_errors.append(msg.text) if msg.type == "error" else None)

        # Navigate to restore page
        page.goto(f"{base_url}/web/restore")
        page.wait_for_load_state("networkidle")

        # Search for tanner
        customer_search = page.locator("#customer-search")
        customer_search.fill("tanner")
        
        # Wait for debounce and results
        page.wait_for_timeout(600)
        
        # Check for results
        results_container = page.locator("#customer-results-container.is-open")
        if not results_container.is_visible():
            pytest.skip("Tanner customer not found in simulation data")
        
        # Select tanner from results
        tanner_result = page.locator(".customer-result-item:has-text('tanner')")
        if tanner_result.count() == 0:
            pytest.skip("Tanner not in customer results")
        
        tanner_result.first.click()
        
        # Wait for HTMX to load backups
        page.wait_for_timeout(1000)
        
        # Verify no JS errors (the null reference bug)
        assert len(js_errors) == 0, f"JavaScript errors: {js_errors}"
        
        # Verify backup title shows Tanner
        backup_title = page.locator("#backup-list-title")
        expect(backup_title).to_have_text("Available Backups for tanner")
        
        # Check for backup rows (may be empty in simulation)
        backup_rows = page.locator("#backup-list tbody tr")
        row_count = backup_rows.count()
        
        # If simulation has backup data, verify at least one row
        if row_count > 0:
            expect(backup_rows.first).to_be_visible()
            
            # Verify backup count indicator updated
            backup_count = page.locator("#backup-count")
            expect(backup_count).not_to_have_text("Loading...")
