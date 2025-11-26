#!/bin/bash
# merge-config.sh - Smart configuration merge for pullDB upgrades
# 
# Merges existing configuration with new template, preserving user values
# while adding new variables and maintaining template structure/comments.
#
# Usage: merge-config.sh <type> <existing> <template> <output>
#   type:     "env" or "ini" (for .aws/config)
#   existing: path to existing config file
#   template: path to new template (env.example, config.example)
#   output:   path to write merged result

set -e

TYPE="$1"
EXISTING="$2"
TEMPLATE="$3"
OUTPUT="$4"

# Validate arguments
if [ -z "$TYPE" ] || [ -z "$EXISTING" ] || [ -z "$TEMPLATE" ] || [ -z "$OUTPUT" ]; then
    echo "Usage: $0 <env|ini> <existing> <template> <output>" >&2
    exit 1
fi

if [ ! -f "$TEMPLATE" ]; then
    echo "Error: Template file not found: $TEMPLATE" >&2
    exit 1
fi

# If no existing file, just copy template
if [ ! -f "$EXISTING" ]; then
    cp "$TEMPLATE" "$OUTPUT"
    echo "Created new config from template"
    exit 0
fi

#------------------------------------------------------------------------------
# ENV file merge (KEY=value format with comments and multi-line support)
#------------------------------------------------------------------------------
merge_env() {
    local existing="$1"
    local template="$2"
    local output="$3"
    
    # Create associative array of existing values
    declare -A existing_values
    local current_key=""
    local current_value=""
    local in_multiline=0
    
    # Parse existing .env file, handling multi-line quoted values
    while IFS= read -r line || [ -n "$line" ]; do
        # Skip empty lines and comments for value extraction
        if [ $in_multiline -eq 1 ]; then
            current_value+=$'\n'"$line"
            # Check if this line ends the multi-line value (ends with ')
            if [[ "$line" =~ ^[^\']*\'[[:space:]]*$ ]] || [[ "$line" =~ ^[^\"]*\"[[:space:]]*$ ]]; then
                existing_values["$current_key"]="$current_value"
                in_multiline=0
                current_key=""
                current_value=""
            fi
        elif [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*) ]]; then
            current_key="${BASH_REMATCH[1]}"
            current_value="${BASH_REMATCH[2]}"
            
            # Check if this starts a multi-line value (starts with ' or " but doesn't end)
            if [[ "$current_value" =~ ^\'[^\']*$ ]] || [[ "$current_value" =~ ^\"[^\"]*$ ]]; then
                in_multiline=1
            else
                existing_values["$current_key"]="$current_value"
                current_key=""
                current_value=""
            fi
        fi
    done < "$existing"
    
    # Track statistics
    local preserved=0
    local added=0
    local total_vars=0
    
    # Process template line by line, substituting existing values
    local output_content=""
    in_multiline=0
    local skip_until_end=0
    local template_key=""
    
    while IFS= read -r line || [ -n "$line" ]; do
        # If we're skipping a multi-line template value (replacing with existing)
        if [ $skip_until_end -eq 1 ]; then
            if [[ "$line" =~ ^[^\']*\'[[:space:]]*$ ]] || [[ "$line" =~ ^[^\"]*\"[[:space:]]*$ ]]; then
                skip_until_end=0
            fi
            continue
        fi
        
        # Check if this is a variable assignment (uncommented)
        if [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*) ]]; then
            template_key="${BASH_REMATCH[1]}"
            local template_value="${BASH_REMATCH[2]}"
            ((total_vars++)) || true
            
            # Check if we have an existing value for this key
            if [ -n "${existing_values[$template_key]+isset}" ]; then
                # Use existing value
                output_content+="${template_key}=${existing_values[$template_key]}"$'\n'
                ((preserved++)) || true
                
                # If template value is multi-line, skip those lines
                if [[ "$template_value" =~ ^\'[^\']*$ ]] || [[ "$template_value" =~ ^\"[^\"]*$ ]]; then
                    skip_until_end=1
                fi
            else
                # New variable - use template value
                output_content+="$line"$'\n'
                ((added++)) || true
                
                # Handle multi-line template values
                if [[ "$template_value" =~ ^\'[^\']*$ ]] || [[ "$template_value" =~ ^\"[^\"]*$ ]]; then
                    in_multiline=1
                fi
            fi
        # Check if this is a COMMENTED variable (# VAR=value) - user may have uncommented version
        elif [[ "$line" =~ ^[[:space:]]*#[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*) ]]; then
            template_key="${BASH_REMATCH[1]}"
            
            # Check if user has an uncommented value for this
            if [ -n "${existing_values[$template_key]+isset}" ]; then
                # User had this enabled - output uncommented with their value
                output_content+="${template_key}=${existing_values[$template_key]}"$'\n'
                ((preserved++)) || true
            else
                # Keep as commented
                output_content+="$line"$'\n'
            fi
        elif [ $in_multiline -eq 1 ]; then
            # Continue multi-line template value for new variable
            output_content+="$line"$'\n'
            if [[ "$line" =~ ^[^\']*\'[[:space:]]*$ ]] || [[ "$line" =~ ^[^\"]*\"[[:space:]]*$ ]]; then
                in_multiline=0
            fi
        else
            # Comment or empty line - preserve from template
            output_content+="$line"$'\n'
        fi
    done < "$template"
    
    # Write output
    printf '%s' "$output_content" > "$output"
    
    echo "Configuration merged:"
    echo "  - Preserved $preserved existing values"
    echo "  - Added $added new variables"
    echo "  - Total variables: $total_vars"
}

#------------------------------------------------------------------------------
# INI file merge (for .aws/config - [section] with key=value)
#------------------------------------------------------------------------------
merge_ini() {
    local existing="$1"
    local template="$2"
    local output="$3"
    
    # Create associative arrays for existing values by section
    declare -A existing_sections  # section -> "key1=val1\nkey2=val2"
    local current_section=""
    local section_content=""
    
    # Parse existing INI file
    while IFS= read -r line || [ -n "$line" ]; do
        # Section header
        if [[ "$line" =~ ^\[([^\]]+)\] ]]; then
            # Save previous section
            if [ -n "$current_section" ]; then
                existing_sections["$current_section"]="$section_content"
            fi
            current_section="${BASH_REMATCH[1]}"
            section_content=""
        elif [ -n "$current_section" ]; then
            # Accumulate section content (skip empty lines)
            if [[ "$line" =~ ^[[:space:]]*[^#[:space:]] ]]; then
                section_content+="$line"$'\n'
            fi
        fi
    done < "$existing"
    # Save last section
    if [ -n "$current_section" ]; then
        existing_sections["$current_section"]="$section_content"
    fi
    
    # Track statistics
    local preserved_sections=0
    local added_sections=0
    
    # Process template, using existing section content where available
    local output_content=""
    current_section=""
    local in_section_content=0
    
    while IFS= read -r line || [ -n "$line" ]; do
        # Section header
        if [[ "$line" =~ ^\[([^\]]+)\] ]]; then
            current_section="${BASH_REMATCH[1]}"
            output_content+="$line"$'\n'
            
            if [ -n "${existing_sections[$current_section]+isset}" ]; then
                # Use existing section content
                output_content+="${existing_sections[$current_section]}"
                ((preserved_sections++)) || true
                in_section_content=1  # Skip template content for this section
            else
                ((added_sections++)) || true
                in_section_content=0  # Use template content
            fi
        elif [ $in_section_content -eq 1 ]; then
            # Skip template content for sections we're using existing values
            if [[ "$line" =~ ^[[:space:]]*$ ]]; then
                # Empty line might signal end of section in template
                output_content+="$line"$'\n'
            fi
            # Skip non-empty content lines (we already added existing content)
            if [[ "$line" =~ ^[[:space:]]*[^#[:space:]] ]]; then
                continue
            fi
            output_content+="$line"$'\n'
        else
            # Use template line (comments, new section content, etc.)
            output_content+="$line"$'\n'
        fi
    done < "$template"
    
    # Write output
    printf '%s' "$output_content" > "$output"
    
    echo "INI configuration merged:"
    echo "  - Preserved $preserved_sections existing sections"
    echo "  - Added $added_sections new sections"
}

#------------------------------------------------------------------------------
# Main
#------------------------------------------------------------------------------
case "$TYPE" in
    env)
        merge_env "$EXISTING" "$TEMPLATE" "$OUTPUT"
        ;;
    ini)
        merge_ini "$EXISTING" "$TEMPLATE" "$OUTPUT"
        ;;
    *)
        echo "Error: Unknown type '$TYPE'. Use 'env' or 'ini'." >&2
        exit 1
        ;;
esac

exit 0
