/**
 * pullDB Help Center - Search Engine
 * Fuzzy search with relevance scoring
 */

// Search configuration
const SEARCH_CONFIG = {
    minQueryLength: 2,
    maxResults: 10,
    fuzzyThreshold: 0.6,
    weights: {
        exactTitle: 100,
        titleContains: 50,
        keywordExact: 30,
        keywordContains: 20,
        contentContains: 10,
        headingContains: 25
    }
};

/**
 * Fuzzy string matching score
 * Returns a score between 0 and 1
 */
function fuzzyMatch(str, pattern) {
    str = str.toLowerCase();
    pattern = pattern.toLowerCase();
    
    // Exact match
    if (str === pattern) return 1;
    
    // Contains match
    if (str.includes(pattern)) {
        // Score based on how early the match appears
        const index = str.indexOf(pattern);
        const positionScore = 1 - (index / str.length);
        return 0.8 + (positionScore * 0.2);
    }
    
    // Fuzzy character matching
    let patternIdx = 0;
    let score = 0;
    let lastMatchIdx = -1;
    
    for (let i = 0; i < str.length && patternIdx < pattern.length; i++) {
        if (str[i] === pattern[patternIdx]) {
            // Bonus for consecutive matches
            if (lastMatchIdx === i - 1) {
                score += 2;
            } else {
                score += 1;
            }
            lastMatchIdx = i;
            patternIdx++;
        }
    }
    
    // All pattern characters must be found
    if (patternIdx !== pattern.length) return 0;
    
    // Normalize score
    const maxPossibleScore = pattern.length * 2;
    return (score / maxPossibleScore) * SEARCH_CONFIG.fuzzyThreshold;
}

/**
 * Calculate relevance score for a search result
 */
function calculateScore(item, query) {
    const queryLower = query.toLowerCase();
    let score = 0;
    
    // Title matching
    const titleLower = item.title.toLowerCase();
    if (titleLower === queryLower) {
        score += SEARCH_CONFIG.weights.exactTitle;
    } else if (titleLower.includes(queryLower)) {
        score += SEARCH_CONFIG.weights.titleContains;
    } else {
        const fuzzyScore = fuzzyMatch(titleLower, queryLower);
        if (fuzzyScore > 0) {
            score += fuzzyScore * SEARCH_CONFIG.weights.titleContains;
        }
    }
    
    // Keyword matching
    if (item.keywords && Array.isArray(item.keywords)) {
        for (const keyword of item.keywords) {
            const keywordLower = keyword.toLowerCase();
            if (keywordLower === queryLower) {
                score += SEARCH_CONFIG.weights.keywordExact;
            } else if (keywordLower.includes(queryLower) || queryLower.includes(keywordLower)) {
                score += SEARCH_CONFIG.weights.keywordContains;
            }
        }
    }
    
    // Content matching
    if (item.content) {
        const contentLower = item.content.toLowerCase();
        if (contentLower.includes(queryLower)) {
            // Bonus for multiple occurrences
            const matches = (contentLower.match(new RegExp(escapeRegex(queryLower), 'g')) || []).length;
            score += SEARCH_CONFIG.weights.contentContains * Math.min(matches, 3);
        }
    }
    
    // Heading matching (if available)
    if (item.headings && Array.isArray(item.headings)) {
        for (const heading of item.headings) {
            if (heading.toLowerCase().includes(queryLower)) {
                score += SEARCH_CONFIG.weights.headingContains;
            }
        }
    }
    
    return score;
}

/**
 * Escape regex special characters
 */
function escapeRegex(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Highlight matching text
 */
function highlightMatches(text, query) {
    if (!query || query.length < 2) return text;
    
    const regex = new RegExp(`(${escapeRegex(query)})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
}

/**
 * Get preview text around the match
 */
function getPreview(content, query, maxLength = 120) {
    if (!content) return '';
    
    const queryLower = query.toLowerCase();
    const contentLower = content.toLowerCase();
    const matchIndex = contentLower.indexOf(queryLower);
    
    if (matchIndex === -1) {
        // No direct match, return start of content
        return content.substring(0, maxLength) + (content.length > maxLength ? '...' : '');
    }
    
    // Calculate window around match
    const contextBefore = 40;
    const contextAfter = maxLength - contextBefore - query.length;
    
    const start = Math.max(0, matchIndex - contextBefore);
    const end = Math.min(content.length, matchIndex + query.length + contextAfter);
    
    let preview = content.substring(start, end);
    
    // Add ellipsis
    if (start > 0) preview = '...' + preview;
    if (end < content.length) preview = preview + '...';
    
    return highlightMatches(preview, query);
}

/**
 * Main search function
 */
function searchDocs(index, query) {
    if (!query || query.length < SEARCH_CONFIG.minQueryLength) {
        return [];
    }
    
    const results = [];
    
    for (const item of index) {
        const score = calculateScore(item, query);
        
        if (score > 0) {
            results.push({
                ...item,
                score,
                highlightedTitle: highlightMatches(item.title, query),
                preview: getPreview(item.content, query)
            });
        }
    }
    
    // Sort by score descending
    results.sort((a, b) => b.score - a.score);
    
    // Return top results
    return results.slice(0, SEARCH_CONFIG.maxResults);
}

/**
 * Debounce function for search input
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Export for use in other files
window.searchDocs = searchDocs;
window.highlightMatches = highlightMatches;
window.getPreview = getPreview;
window.debounce = debounce;
