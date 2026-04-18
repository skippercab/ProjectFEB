"""Embedded Ableton-style audio clip template."""

import xml.etree.ElementTree as ET

_AUDIO_CLIP_TEMPLATE_XML = """<AudioClip Id="1" Time="0">
    <LomId Value="0" />
    <LomIdView Value="0" />
    <CurrentStart Value="0" />
    <CurrentEnd Value="422.29333322927073" />
    <Loop>
        <LoopStart Value="0" />
        <LoopEnd Value="342.39999991562496" />
        <StartRelative Value="0" />
        <LoopOn Value="false" />
        <OutMarker Value="342.39999999999998" />
        <HiddenLoopStart Value="0" />
        <HiddenLoopEnd Value="342.39999999999998" />
    </Loop>
    <Name Value="Guide" />
    <Annotation Value="" />
    <Color Value="13" />
    <LaunchMode Value="0" />
    <LaunchQuantisation Value="0" />
    <TimeSignature>
        <TimeSignatures>
            <RemoteableTimeSignature Id="0">
                <Numerator Value="4" />
                <Denominator Value="4" />
                <Time Value="0" />
            </RemoteableTimeSignature>
        </TimeSignatures>
    </TimeSignature>
    <Envelopes>
        <Envelopes />
    </Envelopes>
    <ScrollerTimePreserver>
        <LeftTime Value="0" />
        <RightTime Value="342.39999991562496" />
    </ScrollerTimePreserver>
    <TimeSelection>
        <AnchorTime Value="0" />
        <OtherTime Value="0" />
    </TimeSelection>
    <Legato Value="false" />
    <Ram Value="false" />
    <GrooveSettings>
        <GrooveId Value="-1" />
    </GrooveSettings>
    <Disabled Value="false" />
    <VelocityAmount Value="0" />
    <FollowAction>
        <FollowTime Value="4" />
        <IsLinked Value="true" />
        <LoopIterations Value="1" />
        <FollowActionA Value="4" />
        <FollowActionB Value="0" />
        <FollowChanceA Value="100" />
        <FollowChanceB Value="0" />
        <JumpIndexA Value="1" />
        <JumpIndexB Value="1" />
        <FollowActionEnabled Value="false" />
    </FollowAction>
    <Grid>
        <FixedNumerator Value="1" />
        <FixedDenominator Value="16" />
        <GridIntervalPixel Value="20" />
        <Ntoles Value="2" />
        <SnapToGrid Value="true" />
        <Fixed Value="false" />
    </Grid>
    <FreezeStart Value="0" />
    <FreezeEnd Value="0" />
    <IsWarped Value="false" />
    <TakeId Value="1" />
    <SampleRef>
        <FileRef>
            <RelativePathType Value="1" />
            <RelativePath Value="" />
            <Path Value="" />
            <Type Value="2" />
            <LivePackName Value="" />
            <LivePackId Value="" />
            <OriginalFileSize Value="0" />
            <OriginalCrc Value="0" />
        </FileRef>
        <LastModDate Value="0" />
        <SourceContext />
        <SampleUsageHint Value="0" />
        <DefaultDuration Value="16435200" />
        <DefaultSampleRate Value="48000" />
    </SampleRef>
    <Onsets>
        <UserOnsets />
        <HasUserOnsets Value="false" />
    </Onsets>
    <WarpMode Value="4" />
    <GranularityTones Value="30" />
    <GranularityTexture Value="65" />
    <FluctuationTexture Value="25" />
    <TransientResolution Value="6" />
    <TransientLoopMode Value="2" />
    <TransientEnvelope Value="100" />
    <ComplexProFormants Value="100" />
    <ComplexProEnvelope Value="128" />
    <Sync Value="true" />
    <HiQ Value="true" />
    <Fade Value="true" />
    <Fades>
        <FadeInLength Value="0" />
        <FadeOutLength Value="0" />
        <ClipFadesAreInitialized Value="true" />
        <CrossfadeInState Value="0" />
        <FadeInCurveSkew Value="0" />
        <FadeInCurveSlope Value="0" />
        <FadeOutCurveSkew Value="0" />
        <FadeOutCurveSlope Value="0" />
        <IsDefaultFadeIn Value="true" />
        <IsDefaultFadeOut Value="true" />
    </Fades>
    <PitchCoarse Value="0" />
    <PitchFine Value="0" />
    <SampleVolume Value="1" />
    <WarpMarkers>
        <WarpMarker Id="14" SecTime="0" BeatTime="0" />
        <WarpMarker Id="15" SecTime="1245.4054054054054" BeatTime="1536" />
        <WarpMarker Id="16" SecTime="1245.431267474371" BeatTime="1536.03125" />
    </WarpMarkers>
    <SavedWarpMarkersForStretched />
    <MarkersGenerated Value="true" />
    <IsSongTempoMaster Value="false" />
</AudioClip>"""


def create_audio_clip_template() -> ET.Element:
    return ET.fromstring(_AUDIO_CLIP_TEMPLATE_XML)