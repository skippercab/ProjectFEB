"""Embedded Ableton-generated blank ReturnTrack XML template."""

import xml.etree.ElementTree as ET

_BLANK_RETURN_TRACK_XML = """<ReturnTrack Id="17">
    <LomId Value="0" />
    <LomIdView Value="0" />
    <IsContentSelectedInDocument Value="false" />
    <PreferredContentViewMode Value="0" />
    <TrackDelay>
        <Value Value="0" />
        <IsValueSampleBased Value="false" />
    </TrackDelay>
    <Name>
        <EffectiveName Value="A-PERC" />
        <UserName Value="PERC" />
        <Annotation Value="" />
        <MemorizedFirstClipName Value="" />
    </Name>
    <Color Value="24" />
    <AutomationEnvelopes>
        <Envelopes />
    </AutomationEnvelopes>
    <TrackGroupId Value="-1" />
    <TrackUnfolded Value="true" />
    <DevicesListWrapper LomId="0" />
    <ClipSlotsListWrapper LomId="0" />
    <ViewData Value="{}" />
    <TakeLanes>
        <TakeLanes />
        <AreTakeLanesFolded Value="true" />
    </TakeLanes>
    <LinkedTrackGroupId Value="-1" />
    <DeviceChain>
        <AutomationLanes>
            <AutomationLanes>
                <AutomationLane Id="0">
                    <SelectedDevice Value="1" />
                    <SelectedEnvelope Value="0" />
                    <IsContentSelectedInDocument Value="false" />
                    <LaneHeight Value="17" />
                </AutomationLane>
            </AutomationLanes>
            <AreAdditionalAutomationLanesFolded Value="false" />
        </AutomationLanes>
        <ClipEnvelopeChooserViewState>
            <SelectedDevice Value="0" />
            <SelectedEnvelope Value="0" />
            <PreferModulationVisible Value="false" />
        </ClipEnvelopeChooserViewState>
        <AudioInputRouting>
            <Target Value="AudioIn/External/S0" />
            <UpperDisplayString Value="Ext. In" />
            <LowerDisplayString Value="1/2" />
            <MpeSettings>
                <ZoneType Value="0" />
                <FirstNoteChannel Value="1" />
                <LastNoteChannel Value="15" />
            </MpeSettings>
        </AudioInputRouting>
        <MidiInputRouting>
            <Target Value="MidiIn/External.All/-1" />
            <UpperDisplayString Value="Ext: All Ins" />
            <LowerDisplayString Value="" />
            <MpeSettings>
                <ZoneType Value="0" />
                <FirstNoteChannel Value="1" />
                <LastNoteChannel Value="15" />
            </MpeSettings>
        </MidiInputRouting>
        <AudioOutputRouting>
            <Target Value="AudioOut/Master" />
            <UpperDisplayString Value="Master" />
            <LowerDisplayString Value="" />
            <MpeSettings>
                <ZoneType Value="0" />
                <FirstNoteChannel Value="1" />
                <LastNoteChannel Value="15" />
            </MpeSettings>
        </AudioOutputRouting>
        <MidiOutputRouting>
            <Target Value="MidiOut/None" />
            <UpperDisplayString Value="None" />
            <LowerDisplayString Value="" />
            <MpeSettings>
                <ZoneType Value="0" />
                <FirstNoteChannel Value="1" />
                <LastNoteChannel Value="15" />
            </MpeSettings>
        </MidiOutputRouting>
        <Mixer>
            <LomId Value="0" />
            <LomIdView Value="0" />
            <IsExpanded Value="true" />
            <On>
                <LomId Value="0" />
                <Manual Value="true" />
                <AutomationTarget Id="22206">
                    <LockEnvelope Value="0" />
                </AutomationTarget>
                <MidiCCOnOffThresholds>
                    <Min Value="64" />
                    <Max Value="127" />
                </MidiCCOnOffThresholds>
            </On>
            <ModulationSourceCount Value="0" />
            <ParametersListWrapper LomId="0" />
            <Pointee Id="22207" />
            <LastSelectedTimeableIndex Value="0" />
            <LastSelectedClipEnvelopeIndex Value="0" />
            <LastPresetRef>
                <Value />
            </LastPresetRef>
            <LockedScripts />
            <IsFolded Value="false" />
            <ShouldShowPresetName Value="true" />
            <UserName Value="" />
            <Annotation Value="" />
            <SourceContext>
                <Value />
            </SourceContext>
            <Sends>
                <TrackSendHolder Id="0">
                    <Send>
                        <LomId Value="0" />
                        <Manual Value="0.0003162277571" />
                        <MidiControllerRange>
                            <Min Value="0.0003162277571" />
                            <Max Value="1" />
                        </MidiControllerRange>
                        <AutomationTarget Id="22235">
                            <LockEnvelope Value="0" />
                        </AutomationTarget>
                        <ModulationTarget Id="22236">
                            <LockEnvelope Value="0" />
                        </ModulationTarget>
                    </Send>
                    <Active Value="false" />
                </TrackSendHolder>
            </Sends>
            <Speaker>
                <LomId Value="0" />
                <KeyMidi>
                    <PersistentKeyString Value="m" />
                    <IsNote Value="false" />
                    <Channel Value="-1" />
                    <NoteOrController Value="-1" />
                    <LowerRangeNote Value="-1" />
                    <UpperRangeNote Value="-1" />
                    <ControllerMapMode Value="0" />
                </KeyMidi>
                <Manual Value="false" />
                <AutomationTarget Id="22208">
                    <LockEnvelope Value="0" />
                </AutomationTarget>
                <MidiCCOnOffThresholds>
                    <Min Value="64" />
                    <Max Value="127" />
                </MidiCCOnOffThresholds>
            </Speaker>
            <SoloSink Value="false" />
            <PanMode Value="0" />
            <Pan>
                <LomId Value="0" />
                <Manual Value="0" />
                <MidiControllerRange>
                    <Min Value="-1" />
                    <Max Value="1" />
                </MidiControllerRange>
                <AutomationTarget Id="22209">
                    <LockEnvelope Value="0" />
                </AutomationTarget>
                <ModulationTarget Id="22210">
                    <LockEnvelope Value="0" />
                </ModulationTarget>
            </Pan>
            <SplitStereoPanL>
                <LomId Value="0" />
                <Manual Value="-1" />
                <MidiControllerRange>
                    <Min Value="-1" />
                    <Max Value="1" />
                </MidiControllerRange>
                <AutomationTarget Id="22211">
                    <LockEnvelope Value="0" />
                </AutomationTarget>
                <ModulationTarget Id="22212">
                    <LockEnvelope Value="0" />
                </ModulationTarget>
            </SplitStereoPanL>
            <SplitStereoPanR>
                <LomId Value="0" />
                <Manual Value="1" />
                <MidiControllerRange>
                    <Min Value="-1" />
                    <Max Value="1" />
                </MidiControllerRange>
                <AutomationTarget Id="22213">
                    <LockEnvelope Value="0" />
                </AutomationTarget>
                <ModulationTarget Id="22214">
                    <LockEnvelope Value="0" />
                </ModulationTarget>
            </SplitStereoPanR>
            <Volume>
                <LomId Value="0" />
                <Manual Value="1" />
                <MidiControllerRange>
                    <Min Value="0.0003162277571" />
                    <Max Value="1.99526238" />
                </MidiControllerRange>
                <AutomationTarget Id="22215">
                    <LockEnvelope Value="0" />
                </AutomationTarget>
                <ModulationTarget Id="22216">
                    <LockEnvelope Value="0" />
                </ModulationTarget>
            </Volume>
            <ViewStateSesstionTrackWidth Value="93" />
            <CrossFadeState>
                <LomId Value="0" />
                <Manual Value="1" />
                <AutomationTarget Id="22217">
                    <LockEnvelope Value="0" />
                </AutomationTarget>
            </CrossFadeState>
            <SendsListWrapper LomId="0" />
        </Mixer>
        <DeviceChain>
            <Devices />
            <SignalModulations />
        </DeviceChain>
        <FreezeSequencer>
            <LomId Value="0" />
            <LomIdView Value="0" />
            <IsExpanded Value="true" />
            <On>
                <LomId Value="0" />
                <Manual Value="true" />
                <AutomationTarget Id="22218">
                    <LockEnvelope Value="0" />
                </AutomationTarget>
                <MidiCCOnOffThresholds>
                    <Min Value="64" />
                    <Max Value="127" />
                </MidiCCOnOffThresholds>
            </On>
            <ModulationSourceCount Value="0" />
            <ParametersListWrapper LomId="0" />
            <Pointee Id="22219" />
            <LastSelectedTimeableIndex Value="0" />
            <LastSelectedClipEnvelopeIndex Value="0" />
            <LastPresetRef>
                <Value />
            </LastPresetRef>
            <LockedScripts />
            <IsFolded Value="false" />
            <ShouldShowPresetName Value="true" />
            <UserName Value="" />
            <Annotation Value="" />
            <SourceContext>
                <Value />
            </SourceContext>
            <ClipSlotList />
            <MonitoringEnum Value="1" />
            <Sample>
                <ArrangerAutomation>
                    <Events />
                    <AutomationTransformViewState>
                        <IsTransformPending Value="false" />
                        <TimeAndValueTransforms />
                    </AutomationTransformViewState>
                </ArrangerAutomation>
            </Sample>
            <VolumeModulationTarget Id="22220">
                <LockEnvelope Value="0" />
            </VolumeModulationTarget>
            <TranspositionModulationTarget Id="22221">
                <LockEnvelope Value="0" />
            </TranspositionModulationTarget>
            <GrainSizeModulationTarget Id="22222">
                <LockEnvelope Value="0" />
            </GrainSizeModulationTarget>
            <FluxModulationTarget Id="22223">
                <LockEnvelope Value="0" />
            </FluxModulationTarget>
            <SampleOffsetModulationTarget Id="22224">
                <LockEnvelope Value="0" />
            </SampleOffsetModulationTarget>
            <PitchViewScrollPosition Value="-1073741824" />
            <SampleOffsetModulationScrollPosition Value="-1073741824" />
            <Recorder>
                <IsArmed Value="false" />
                <TakeCounter Value="1" />
            </Recorder>
        </FreezeSequencer>
    </DeviceChain>
</ReturnTrack>"""


def create_blank_return_track_template() -> ET.Element:
    return ET.fromstring(_BLANK_RETURN_TRACK_XML)
