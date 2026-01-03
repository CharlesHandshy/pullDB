/**
 * pullDB Help Center - Animated Terminal Component
 * Creates realistic typing animations for terminal demos
 */

// Hero terminal animation sequence - matches actual CLI output
const heroTerminalSequence = [
    { type: 'prompt', delay: 0 },
    { type: 'type', text: 'pulldb restore acme', delay: 0 },
    { type: 'output', html: 'Job queued successfully!', delay: 800 },
    { type: 'output', html: '  customer:     acme', delay: 200 },
    { type: 'output', html: '  target:       <span class="highlight">chrlesacme</span>', delay: 200 },
    { type: 'output', html: '  staging_name: chrlesacme7f3a2b1c', delay: 200 },
    { type: 'output', html: '  job_id:       <span class="highlight">7f3a2b1c</span>-85a1-4da2-...', delay: 200 },
    { type: 'output', html: '  status:       queued', delay: 200 },
    { type: 'output', html: '  user:         charles (chrles)', delay: 200 },
    { type: 'output', html: '', delay: 100 },
    { type: 'output', html: 'Use \'pulldb status\' to monitor progress.', delay: 200 },
    { type: 'pause', delay: 2000 },
    { type: 'prompt', delay: 0 },
    { type: 'type', text: 'pulldb status', delay: 0 },
    { type: 'output', html: 'Your last submitted job:', delay: 600 },
    { type: 'output', html: '', delay: 100 },
    { type: 'output', html: '  STATUS   : <span class="status-badge running">running</span>', delay: 200 },
    { type: 'output', html: '  OPERATION: Restore progress', delay: 200 },
    { type: 'output', html: '  JOB_ID   : <span class="highlight">7f3a2b1c</span>', delay: 200 },
    { type: 'output', html: '  CUSTOMER : acme', delay: 200 },
    { type: 'output', html: '  TARGET   : chrlesacme', delay: 200 },
    { type: 'pause', delay: 2500 },
    { type: 'prompt', delay: 0 },
    { type: 'type', text: 'pulldb status', delay: 0 },
    { type: 'output', html: 'Your last submitted job:', delay: 600 },
    { type: 'output', html: '', delay: 100 },
    { type: 'output', html: '  STATUS   : <span class="status-badge complete">complete</span>', delay: 200 },
    { type: 'output', html: '  OPERATION: Restore complete', delay: 200 },
    { type: 'output', html: '  JOB_ID   : <span class="highlight">7f3a2b1c</span>', delay: 200 },
    { type: 'output', html: '  CUSTOMER : acme', delay: 200 },
    { type: 'output', html: '  TARGET   : <span class="highlight">chrlesacme</span>', delay: 200 },
    { type: 'pause', delay: 3000 },
    { type: 'clear', delay: 0 }
];

// Terminal animation state
let heroAnimationRunning = false;

// Initialize hero terminal
function initHeroTerminal() {
    const container = document.getElementById('hero-terminal-body');
    if (!container || heroAnimationRunning) return;
    
    heroAnimationRunning = true;
    runTerminalSequence(container, heroTerminalSequence, true);
}

// Run a terminal animation sequence
async function runTerminalSequence(container, sequence, loop = false) {
    while (true) {
        container.innerHTML = '';
        
        for (const step of sequence) {
            await delay(step.delay);
            
            switch (step.type) {
                case 'prompt':
                    const promptLine = createLine();
                    promptLine.innerHTML = '<span class="prompt">$</span> <span class="cursor">▋</span>';
                    container.appendChild(promptLine);
                    break;
                    
                case 'type':
                    await typeText(container, step.text);
                    break;
                    
                case 'output':
                    const outputLine = createLine('output');
                    outputLine.innerHTML = step.html;
                    container.appendChild(outputLine);
                    scrollToBottom(container);
                    break;
                    
                case 'pause':
                    // Just wait
                    break;
                    
                case 'clear':
                    // Clear will happen at start of next loop
                    break;
            }
        }
        
        if (!loop) break;
        await delay(1000);
    }
}

// Create a terminal line element
function createLine(className = '') {
    const line = document.createElement('div');
    line.className = 'terminal-line' + (className ? ' ' + className : '');
    return line;
}

// Type text character by character
async function typeText(container, text) {
    // Get the last line (which should have the prompt and cursor)
    const lastLine = container.lastElementChild;
    if (!lastLine) return;
    
    // Remove cursor, add command span
    lastLine.innerHTML = '<span class="prompt">$</span> <span class="command"></span><span class="cursor">▋</span>';
    const commandSpan = lastLine.querySelector('.command');
    const cursorSpan = lastLine.querySelector('.cursor');
    
    // Type each character
    for (let i = 0; i < text.length; i++) {
        commandSpan.textContent += text[i];
        await delay(getTypeDelay());
    }
    
    // Remove cursor after typing
    await delay(200);
    cursorSpan.remove();
}

// Get random typing delay for realistic effect
function getTypeDelay() {
    // Base delay with some randomness
    const base = 40;
    const variance = 30;
    return base + Math.random() * variance;
}

// Scroll container to bottom
function scrollToBottom(container) {
    container.scrollTop = container.scrollHeight;
}

// Promise-based delay
function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// Interactive terminal component for demos
class InteractiveTerminal {
    constructor(containerId, commands) {
        this.container = document.getElementById(containerId);
        this.commands = commands;
        this.currentCommand = 0;
        
        if (this.container) {
            this.init();
        }
    }
    
    init() {
        this.container.innerHTML = '';
        this.runNextCommand();
    }
    
    async runNextCommand() {
        if (this.currentCommand >= this.commands.length) {
            this.currentCommand = 0;
            await delay(2000);
            this.init();
            return;
        }
        
        const cmd = this.commands[this.currentCommand];
        
        // Show prompt
        const promptLine = createLine();
        promptLine.innerHTML = '<span class="prompt">$</span> <span class="cursor">▋</span>';
        this.container.appendChild(promptLine);
        
        await delay(500);
        
        // Type command
        await typeText(this.container, cmd.input);
        
        await delay(300);
        
        // Show output
        for (const output of cmd.output) {
            const outputLine = createLine('output');
            outputLine.innerHTML = output;
            this.container.appendChild(outputLine);
            await delay(150);
        }
        
        this.currentCommand++;
        
        // Wait before next command
        await delay(cmd.pauseAfter || 2000);
        this.runNextCommand();
    }
}

// Playable terminal demo (click to replay)
function initPlayableTerminal(containerId, sequence) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    const wrapper = container.closest('.demo-terminal');
    if (wrapper) {
        const replayBtn = document.createElement('button');
        replayBtn.className = 'terminal-replay';
        replayBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="1 4 1 10 7 10"/>
                <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>
            </svg>
            Replay
        `;
        replayBtn.onclick = () => runTerminalSequence(container, sequence, false);
        
        const header = wrapper.querySelector('.terminal-header');
        if (header) {
            header.appendChild(replayBtn);
        }
    }
}

// Export for use in other files
window.initHeroTerminal = initHeroTerminal;
window.InteractiveTerminal = InteractiveTerminal;
window.initPlayableTerminal = initPlayableTerminal;
window.runTerminalSequence = runTerminalSequence;
